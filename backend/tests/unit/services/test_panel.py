from __future__ import annotations

import json
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from habitusx.adapters.bigquery.gateway import BigQueryGateway
from habitusx.adapters.github.client import GitHubGraphQL
from habitusx.adapters.parquet import read_table, write_observations
from habitusx.adapters.parquet_panel import COMMITS_SCHEMA, PULLS_SCHEMA, REPOS_SCHEMA
from habitusx.domain.observations import CommitObservation, hash_identity
from habitusx.domain.panel import Cohort, Panel, PanelMember, sample_key
from habitusx.registry import load_registry
from habitusx.services.panel import (
    PanelError,
    control_candidates,
    fetch_panel,
    load_panel,
    panel_output_dir,
    save_panel,
    treated_candidates,
)
from tests.fakes import (
    CLAUDE_TRAILER_MSG,
    SHA_A,
    SHA_B,
    SHA_C,
    FakeClient,
    FakeTransport,
    fake_job_config,
    gql_commit,
    gql_pull,
    gql_repo,
    gql_response,
)

DAY = date(2026, 9, 5)
SINCE = datetime(2026, 9, 1, tzinfo=UTC)


def member(repo: str, cohort: Cohort = Cohort.TREATED) -> PanelMember:
    return PanelMember(
        repo=repo, cohort=cohort, added_on=DAY, source="s", sample_key=sample_key(repo)
    )


def panel(*members: PanelMember) -> Panel:
    return Panel(version=1, created_on=DAY, treated_rate=1.0, control_rate=1.0, members=members)


class TestBuildInputs:
    def test_treated_candidates_reads_every_census_day(self, tmp_path: Path) -> None:
        def obs(repo: str, agent: str | None, sha: str) -> CommitObservation:
            return CommitObservation(
                day=date(2025, 9, 1),
                registry_version=1,
                event_id="1",
                repo=repo,
                sha=sha,
                pushed_at=datetime(2025, 9, 1, tzinfo=UTC),
                is_distinct=True,
                push_size=1,
                subject="s",
                message="m",
                is_revert=False,
                revert=None,
                author_email_hash=None,
                author_name_hash=None,
                pusher_login_hash=None,
                pusher_is_bot=False,
                attribution=None,
                agent_id=agent,
                matched_prefilter=agent is not None,
                commits_in_repo_day=1,
            )

        root = tmp_path / "observations"
        write_observations(
            [obs("a/ai", "claude-code", SHA_A), obs("b/human", None, SHA_B)],
            root / "day=2025-09-01" / "commits.parquet",
        )
        write_observations(
            [obs("c/ai", "cursor", SHA_C)], root / "day=2025-09-02" / "commits.parquet"
        )
        assert treated_candidates(root) == {"a/ai", "c/ai"}

    def test_control_candidates_from_archive(self) -> None:
        client = FakeClient(
            estimate_bytes=1, rows=[{"repo": "x/y"}, {"repo": "z/w"}, {"repo": None}]
        )
        gateway = BigQueryGateway(
            client, max_bytes_billed=10**9, job_config_factory=fake_job_config
        )
        assert control_candidates(date(2026, 8, 25), gateway=gateway) == {"x/y", "z/w"}
        assert "githubarchive.day.20260825" in client.calls[1]["sql"]

    def test_save_and_load_panel(self, tmp_path: Path) -> None:
        p = panel(member("a/b"), member("c/d", Cohort.CONTROL))
        path = tmp_path / "panel" / "panel_v1.json"
        save_panel(p, path)
        assert load_panel(path) == p

    def test_load_panel_errors_are_typed(self, tmp_path: Path) -> None:
        with pytest.raises(PanelError, match="cannot read"):
            load_panel(tmp_path / "missing.json")
        bad = tmp_path / "bad.json"
        bad.write_text('{"version": 0}', encoding="utf-8")
        with pytest.raises(PanelError, match="invalid"):
            load_panel(bad)


class TestFetchPanel:
    def test_end_to_end_with_attribution_and_attrition(
        self, registry_path: Path, tmp_path: Path
    ) -> None:
        registry = load_registry(registry_path)
        # Repo A: a Claude Code commit and a PR opened by Claude Code (footer in body).
        # Repo B: gone. Repo C: control repo with a human commit and a revert PR by Copilot.
        repo_a = gql_repo(
            "a/ai",
            commits=[gql_commit(SHA_A, CLAUDE_TRAILER_MSG, pr_number=7)],
            pulls=[
                gql_pull(
                    7,
                    "Add retry",
                    body="Summary...\n\n🤖 Generated with [Claude Code](https://claude.com/claude-code)",
                )
            ],
            language="Python",
        )
        repo_c = gql_repo(
            "c/control",
            commits=[gql_commit(SHA_C, "Tidy imports", login="human")],
            pulls=[
                gql_pull(
                    15,
                    'Revert "Add thing (#12)"',
                    login="Copilot",
                    is_bot=True,
                    merged=False,
                    merge_sha=None,
                )
            ],
            language="Go",
        )
        transport = FakeTransport(
            [
                gql_response({"r0": repo_a, "r1": None}, cost=2, remaining=4998),
                gql_response({"r0": repo_c}, cost=1, remaining=4997),
            ]
        )
        client = GitHubGraphQL(transport)
        p = panel(member("a/ai"), member("b/gone"), member("c/control", Cohort.CONTROL))

        summary = fetch_panel(
            p,
            client=client,
            registry=registry,
            since=SINCE,
            fetched_on=DAY,
            out_dir=tmp_path,
            batch_size=2,
        )

        assert summary.repos_requested == 3
        assert summary.repos_by_status == {"not_found": 1, "ok": 2}
        assert summary.commits == 2
        assert summary.commits_attributed == 1
        assert summary.commits_by_agent == {"claude-code": 1}
        assert summary.pulls == 2
        assert summary.pulls_attributed == 2
        assert summary.pulls_by_agent == {"claude-code": 1, "github-copilot": 1}
        assert summary.points_spent == 3
        assert summary.requests_made == 2

        out = panel_output_dir(tmp_path, DAY)
        repos = read_table(out / "repos.parquet", REPOS_SCHEMA)
        commits = read_table(out / "commits.parquet", COMMITS_SCHEMA)
        pulls = read_table(out / "pulls.parquet", PULLS_SCHEMA)

        assert {r["repo"]: r["status"] for r in repos} == {
            "a/ai": "ok",
            "b/gone": "not_found",
            "c/control": "ok",
        }
        assert {r["repo"]: r["cohort"] for r in repos}["c/control"] == "control"
        assert {r["repo"]: r["primary_language"] for r in repos}["c/control"] == "Go"

        claude_commit = next(c for c in commits if c["sha"] == SHA_A)
        assert claude_commit["agent_id"] == "claude-code"
        assert claude_commit["associated_pr_number"] == 7
        assert claude_commit["author_login_hash"] == hash_identity("octocat")
        serialised = json.dumps(commits, default=str)
        assert "octocat" not in serialised
        assert "octo@example.com" not in serialised

        claude_pr = next(p_ for p_ in pulls if p_["number"] == 7)
        assert claude_pr["agent_id"] == "claude-code"
        assert claude_pr["merged"] is True
        assert claude_pr["merge_commit_sha"] == SHA_B
        revert_pr = next(p_ for p_ in pulls if p_["number"] == 15)
        assert revert_pr["is_revert"] is True
        assert revert_pr["original_pr_number"] == 12
        assert revert_pr["agent_id"] == "github-copilot"
        assert revert_pr["author_is_bot"] is True

        manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
        assert manifest["panel"] == {
            "version": 1,
            "created_on": "2026-09-05",
            "members_total": 3,
            "members_fetched": 3,
            "treated_rate": 1.0,
            "control_rate": 1.0,
        }
        assert manifest["repos_by_status"] == {"not_found": 1, "ok": 2}
        assert manifest["github"] == {"points_spent": 3, "requests": 2}
        assert manifest["commits_by_agent"] == {"claude-code": 1}

    def test_limit_restricts_members(self, registry_path: Path, tmp_path: Path) -> None:
        transport = FakeTransport([gql_response({"r0": gql_repo("a/ai")})])
        summary = fetch_panel(
            panel(member("a/ai"), member("b/b")),
            client=GitHubGraphQL(transport),
            registry=load_registry(registry_path),
            since=SINCE,
            fetched_on=DAY,
            out_dir=tmp_path,
            limit=1,
        )
        assert summary.repos_requested == 1
        assert len(transport.calls) == 1

    def test_requires_aware_since(self, registry_path: Path, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match="timezone-aware"):
            fetch_panel(
                panel(member("a/ai")),
                client=GitHubGraphQL(FakeTransport([])),
                registry=load_registry(registry_path),
                since=datetime(2026, 9, 1),
                fetched_on=DAY,
                out_dir=tmp_path,
            )
