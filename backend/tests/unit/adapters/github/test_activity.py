from __future__ import annotations

from datetime import UTC, datetime

import pytest

from habitusx.adapters.github.activity import (
    fetch_activity,
    parse_commit,
    parse_pull,
    parse_repository,
    render_batch_query,
    render_history_page_query,
)
from habitusx.adapters.github.client import GitHubGraphQL
from habitusx.domain.panel_observations import FetchStatus
from tests.fakes import (
    CLAUDE_TRAILER_MSG,
    SHA_A,
    SHA_B,
    SHA_C,
    FakeTransport,
    gql_commit,
    gql_pull,
    gql_repo,
    gql_response,
)

SINCE = datetime(2026, 9, 1, tzinfo=UTC)


class TestRendering:
    def test_batch_query_has_one_alias_per_repo_and_a_since_variable(self) -> None:
        q = render_batch_query(["octo/repo", "acme/tool"], history_first=100, prs_first=50)
        assert 'r0: repository(owner: "octo", name: "repo")' in q
        assert 'r1: repository(owner: "acme", name: "tool")' in q
        assert "query RepoActivity($since: GitTimestamp!)" in q
        assert "rateLimit { cost remaining resetAt }" in q
        assert "history(first: 100, since: $since)" in q
        assert "pullRequests(first: 50" in q
        assert "{{" not in q

    def test_history_page_query(self) -> None:
        q = render_history_page_query("octo/repo", history_first=100)
        assert "$after: String!" in q
        assert 'repository(owner: "octo", name: "repo")' in q


class TestParsers:
    def test_parse_commit_with_bot_author_and_pr(self) -> None:
        raw = parse_commit(gql_commit(login="copilot-swe-agent[bot]", is_bot=True, pr_number=12))
        assert raw.sha == SHA_A
        assert raw.author_login == "copilot-swe-agent[bot]"
        assert raw.author_is_bot is True
        assert raw.associated_pr_number == 12
        assert raw.committed_at.tzinfo is not None

    def test_parse_commit_without_github_user(self) -> None:
        raw = parse_commit(gql_commit(login=None))
        assert raw.author_login is None
        assert raw.author_is_bot is False

    def test_parse_pull(self) -> None:
        raw = parse_pull(gql_pull(number=9, merged=False, merge_sha=None))
        assert raw.number == 9
        assert raw.merged is False
        assert raw.merged_at is None
        assert raw.merge_commit_sha is None
        assert raw.review_count == 1
        assert raw.comment_count == 2

    def test_parse_repository_not_found(self) -> None:
        activity, cursor = parse_repository(
            "gone/repo", None, error_type="NOT_FOUND", since=SINCE, prs_first=50
        )
        assert activity.status is FetchStatus.NOT_FOUND
        assert cursor is None

    def test_parse_repository_other_error(self) -> None:
        activity, _ = parse_repository("x/y", None, error_type=None, since=SINCE, prs_first=50)
        assert activity.status is FetchStatus.ERROR

    def test_parse_repository_empty_branch(self) -> None:
        activity, _ = parse_repository(
            "x/y", gql_repo(no_branch=True), error_type=None, since=SINCE, prs_first=50
        )
        assert activity.status is FetchStatus.EMPTY
        assert activity.commits == ()

    def test_pulls_filtered_by_since_and_truncation_flag(self) -> None:
        old = gql_pull(number=1, updated_at="2026-08-01T00:00:00Z")
        new = gql_pull(number=2, updated_at="2026-09-02T00:00:00Z")
        activity, _ = parse_repository(
            "x/y", gql_repo(pulls=[new, old]), error_type=None, since=SINCE, prs_first=2
        )
        assert [p.number for p in activity.pulls] == [2]
        assert activity.pulls_truncated is False  # an old PR was seen, so nothing was cut

        activity, _ = parse_repository(
            "x/y", gql_repo(pulls=[new, new]), error_type=None, since=SINCE, prs_first=2
        )
        assert activity.pulls_truncated is True  # full page, all new: older ones may be missing

    def test_history_cursor_returned_when_more_pages(self) -> None:
        node = gql_repo(commits=[gql_commit()], has_next=True, cursor="CUR1", total=250)
        activity, cursor = parse_repository("x/y", node, error_type=None, since=SINCE, prs_first=50)
        assert cursor == "CUR1"
        assert activity.commits_truncated is True
        assert activity.commits_total == 250


class TestFetchActivity:
    def test_batches_and_reports_not_found(self) -> None:
        transport = FakeTransport(
            [
                gql_response({"r0": gql_repo("a/a", commits=[gql_commit()]), "r1": None}),
                gql_response({"r0": gql_repo("c/c", pulls=[gql_pull()])}),
            ]
        )
        client = GitHubGraphQL(transport)
        results = fetch_activity(client, ["a/a", "b/b", "c/c"], since=SINCE, batch_size=2)
        assert [r.status for r in results] == [
            FetchStatus.OK,
            FetchStatus.NOT_FOUND,
            FetchStatus.OK,
        ]
        assert results[0].commits[0].sha == SHA_A
        assert results[2].pulls[0].number == 7
        assert len(transport.calls) == 2
        assert transport.calls[0][1] == {"since": "2026-09-01T00:00:00Z"}

    def test_follows_history_pages_up_to_the_cap(self) -> None:
        page1 = gql_response(
            {"r0": gql_repo(commits=[gql_commit(SHA_A)], has_next=True, cursor="C1", total=3)}
        )
        page2 = {
            "data": {
                "rateLimit": {"cost": 1, "remaining": 4000, "resetAt": "2026-09-05T13:00:00Z"},
                "repository": {
                    "defaultBranchRef": {
                        "target": {
                            "history": {
                                "pageInfo": {"hasNextPage": True, "endCursor": "C2"},
                                "nodes": [gql_commit(SHA_B)],
                            }
                        }
                    }
                },
            }
        }
        page3 = {
            "data": {
                "rateLimit": {"cost": 1, "remaining": 3999, "resetAt": "2026-09-05T13:00:00Z"},
                "repository": {
                    "defaultBranchRef": {
                        "target": {
                            "history": {
                                "pageInfo": {"hasNextPage": False, "endCursor": None},
                                "nodes": [gql_commit(SHA_C)],
                            }
                        }
                    }
                },
            }
        }
        transport = FakeTransport([page1, page2, page3])
        [activity] = fetch_activity(
            GitHubGraphQL(transport), ["x/y"], since=SINCE, max_history_pages=5
        )
        assert [c.sha for c in activity.commits] == [SHA_A, SHA_B, SHA_C]
        assert activity.commits_truncated is False
        assert transport.calls[1][1]["after"] == "C1"
        assert transport.calls[2][1]["after"] == "C2"

    def test_stops_at_max_pages_and_flags_truncation(self) -> None:
        page1 = gql_response(
            {"r0": gql_repo(commits=[gql_commit(SHA_A)], has_next=True, cursor="C1")}
        )
        page2 = {
            "data": {
                "rateLimit": {"cost": 1, "remaining": 4000, "resetAt": "2026-09-05T13:00:00Z"},
                "repository": {
                    "defaultBranchRef": {
                        "target": {
                            "history": {
                                "pageInfo": {"hasNextPage": True, "endCursor": "C2"},
                                "nodes": [gql_commit(SHA_B)],
                            }
                        }
                    }
                },
            }
        }
        transport = FakeTransport([page1, page2])
        [activity] = fetch_activity(
            GitHubGraphQL(transport), ["x/y"], since=SINCE, max_history_pages=1
        )
        assert [c.sha for c in activity.commits] == [SHA_A, SHA_B]
        assert activity.commits_truncated is True

    def test_trailer_survives_parsing(self) -> None:
        transport = FakeTransport(
            [gql_response({"r0": gql_repo(commits=[gql_commit(message=CLAUDE_TRAILER_MSG)])})]
        )
        [activity] = fetch_activity(GitHubGraphQL(transport), ["x/y"], since=SINCE)
        assert "noreply@anthropic.com" in activity.commits[0].message

    @pytest.mark.parametrize(
        ("history_first", "prs_first"), [(0, 50), (101, 50), (50, 0), (50, 101)]
    )
    def test_page_size_bounds(self, history_first: int, prs_first: int) -> None:
        with pytest.raises(ValueError, match="between 1 and 100"):
            fetch_activity(
                GitHubGraphQL(FakeTransport([])),
                ["x/y"],
                since=SINCE,
                history_first=history_first,
                prs_first=prs_first,
            )
