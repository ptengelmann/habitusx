"""Fetch one batch of repositories' recent activity and parse it into typed rows.

GraphQL aliases let several repositories share one request. Repositories that no longer
resolve come back as per-alias ``NOT_FOUND`` errors and are reported as such rather than
failing the batch; that is the attrition signal.
"""

from __future__ import annotations

import re
from datetime import datetime
from importlib import resources
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, ConfigDict, Field

from habitusx.domain.commits import RepoFullName
from habitusx.domain.panel_observations import FetchStatus
from habitusx.logging import get_logger

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

    from habitusx.adapters.github.client import GitHubGraphQL

log = get_logger(__name__)

_TEMPLATE_TOKEN = re.compile(r"\{\{\s*(\w+)\s*\}\}")
_MAX_HISTORY_FIRST = 100
_MAX_PRS_FIRST = 100


class RawCommit(BaseModel):
    """A commit as GitHub returned it, before attribution."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    sha: str
    committed_at: datetime
    subject: str
    message: str
    author_name: str | None
    author_email: str | None
    author_login: str | None
    author_is_bot: bool
    associated_pr_number: int | None


class RawPullRequest(BaseModel):
    """A pull request as GitHub returned it, before attribution."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    number: int
    title: str
    body: str
    state: str
    created_at: datetime
    updated_at: datetime
    closed_at: datetime | None
    merged_at: datetime | None
    merged: bool
    author_login: str | None
    author_is_bot: bool
    additions: int | None
    deletions: int | None
    changed_files: int | None
    review_count: int
    comment_count: int
    review_thread_count: int
    merge_commit_sha: str | None


class RepoActivity(BaseModel):
    """Everything fetched for one repository in one pass."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    repo: RepoFullName = Field(description="The name we asked for.")
    status: FetchStatus
    name_with_owner: str | None = Field(
        default=None, description="The name GitHub reports; differs after a rename."
    )
    repo_id: int | None = None
    is_fork: bool | None = None
    stargazers: int | None = None
    primary_language: str | None = None
    default_branch: str | None = None
    commits: tuple[RawCommit, ...] = ()
    commits_total: int | None = None
    commits_truncated: bool = False
    pulls: tuple[RawPullRequest, ...] = ()
    pulls_truncated: bool = False
    error: str | None = None


def _load(name: str) -> str:
    return (resources.files(__package__) / "graphql" / f"{name}.graphql").read_text(
        encoding="utf-8"
    )


def _render(template: str, values: dict[str, str]) -> str:
    def replace(match: re.Match[str]) -> str:
        key = match.group(1)
        if key not in values:
            msg = f"GraphQL template references unknown value {{{{ {key} }}}}"
            raise KeyError(msg)
        return values[key]

    return _TEMPLATE_TOKEN.sub(replace, template)


def _split(repo: str) -> tuple[str, str]:
    owner, name = repo.split("/", 1)
    return owner, name


def render_batch_query(repos: Sequence[str], *, history_first: int, prs_first: int) -> str:
    """One request covering ``repos``, each under alias ``r<i>``."""
    fragment = _load("repo_activity")
    body = "\n".join(
        _render(
            fragment,
            {
                "alias": f"r{i}",
                "owner": _split(r)[0],
                "name": _split(r)[1],
                "history_first": str(history_first),
                "prs_first": str(prs_first),
            },
        )
        for i, r in enumerate(repos)
    )
    return (
        "query RepoActivity($since: GitTimestamp!) {\n"
        "  rateLimit { cost remaining resetAt }\n" + body + "\n}"
    )


def render_history_page_query(repo: str, *, history_first: int) -> str:
    """Follow-up history page for one repository."""
    owner, name = _split(repo)
    return _render(
        _load("history_page"),
        {"owner": owner, "name": name, "history_first": str(history_first)},
    )


def _ts(value: object) -> datetime:
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def _opt_ts(value: object) -> datetime | None:
    return _ts(value) if value else None


def parse_commit(node: dict[str, Any]) -> RawCommit:
    """Parse one history node."""
    author = node.get("author") or {}
    user = author.get("user") or {}
    prs = ((node.get("associatedPullRequests") or {}).get("nodes")) or []
    return RawCommit(
        sha=str(node["oid"]),
        committed_at=_ts(node["committedDate"]),
        subject=str(node.get("messageHeadline") or ""),
        message=str(node.get("message") or ""),
        author_name=author.get("name"),
        author_email=author.get("email"),
        author_login=user.get("login"),
        author_is_bot=(user.get("__typename") == "Bot"),
        associated_pr_number=int(prs[0]["number"]) if prs else None,
    )


def parse_pull(node: dict[str, Any]) -> RawPullRequest:
    """Parse one pull request node."""
    author = node.get("author") or {}
    merge_commit = node.get("mergeCommit") or {}
    return RawPullRequest(
        number=int(node["number"]),
        title=str(node.get("title") or ""),
        body=str(node.get("body") or ""),
        state=str(node.get("state") or ""),
        created_at=_ts(node["createdAt"]),
        updated_at=_ts(node["updatedAt"]),
        closed_at=_opt_ts(node.get("closedAt")),
        merged_at=_opt_ts(node.get("mergedAt")),
        merged=bool(node.get("merged")),
        author_login=author.get("login"),
        author_is_bot=(author.get("__typename") == "Bot"),
        additions=node.get("additions"),
        deletions=node.get("deletions"),
        changed_files=node.get("changedFiles"),
        review_count=int((node.get("reviews") or {}).get("totalCount") or 0),
        comment_count=int((node.get("comments") or {}).get("totalCount") or 0),
        review_thread_count=int((node.get("reviewThreads") or {}).get("totalCount") or 0),
        merge_commit_sha=merge_commit.get("oid"),
    )


def parse_repository(
    repo: str,
    node: dict[str, Any] | None,
    *,
    error_type: str | None,
    since: datetime,
    prs_first: int,
) -> tuple[RepoActivity, str | None]:
    """Turn one alias's data into a RepoActivity plus the history cursor if more pages exist."""
    if node is None:
        status = FetchStatus.NOT_FOUND if error_type == "NOT_FOUND" else FetchStatus.ERROR
        return RepoActivity(repo=repo, status=status, error=error_type or "no data"), None

    branch = node.get("defaultBranchRef")
    history = ((branch or {}).get("target") or {}).get("history") or {}
    page_info = history.get("pageInfo") or {}
    commits = tuple(parse_commit(n) for n in history.get("nodes") or [])

    pulls_all = [parse_pull(n) for n in (node.get("pullRequests") or {}).get("nodes") or []]
    pulls = tuple(p for p in pulls_all if p.updated_at >= since)
    # We asked for the prs_first most recently updated PRs. If the page was full and every
    # one of them is newer than the watermark, older qualifying PRs may have been cut off.
    pulls_truncated = (
        len(pulls_all) >= prs_first and len(pulls) == len(pulls_all) and bool(pulls_all)
    )

    activity = RepoActivity(
        repo=repo,
        status=FetchStatus.OK if branch else FetchStatus.EMPTY,
        name_with_owner=node.get("nameWithOwner"),
        repo_id=node.get("databaseId"),
        is_fork=node.get("isFork"),
        stargazers=node.get("stargazerCount"),
        primary_language=((node.get("primaryLanguage") or {}).get("name")),
        default_branch=(branch or {}).get("name"),
        commits=commits,
        commits_total=history.get("totalCount"),
        commits_truncated=bool(page_info.get("hasNextPage")),
        pulls=pulls,
        pulls_truncated=pulls_truncated,
    )
    cursor = page_info.get("endCursor") if page_info.get("hasNextPage") else None
    return activity, cursor


def fetch_activity(
    client: GitHubGraphQL,
    repos: Iterable[str],
    *,
    since: datetime,
    batch_size: int = 5,
    history_first: int = 100,
    prs_first: int = 50,
    max_history_pages: int = 5,
) -> list[RepoActivity]:
    """Fetch activity for every repository, in batches, following history pages as needed.

    Repositories that fail to resolve are returned with ``status`` NOT_FOUND or ERROR; the
    batch continues. Commits beyond ``max_history_pages`` are dropped and the repository is
    marked ``commits_truncated`` so the gap is visible.
    """
    if not 1 <= history_first <= _MAX_HISTORY_FIRST or not 1 <= prs_first <= _MAX_PRS_FIRST:
        msg = "page sizes must be between 1 and 100"
        raise ValueError(msg)
    repo_list = list(repos)
    since_iso = since.isoformat().replace("+00:00", "Z")
    results: list[RepoActivity] = []

    for start in range(0, len(repo_list), max(1, batch_size)):
        chunk = repo_list[start : start + batch_size]
        query = render_batch_query(chunk, history_first=history_first, prs_first=prs_first)
        response = client.execute(query, {"since": since_iso})
        error_types = response.error_paths()

        for i, repo in enumerate(chunk):
            alias = f"r{i}"
            activity, cursor = parse_repository(
                repo,
                response.data.get(alias),
                error_type=error_types.get(alias),
                since=since,
                prs_first=prs_first,
            )
            pages = 0
            while cursor and pages < max_history_pages:
                page = client.execute(
                    render_history_page_query(repo, history_first=history_first),
                    {"since": since_iso, "after": cursor},
                )
                history = (
                    ((page.data.get("repository") or {}).get("defaultBranchRef") or {})
                    .get("target", {})
                    .get("history", {})
                )
                more = tuple(parse_commit(n) for n in history.get("nodes") or [])
                info = history.get("pageInfo") or {}
                cursor = info.get("endCursor") if info.get("hasNextPage") else None
                pages += 1
                activity = activity.model_copy(
                    update={
                        "commits": activity.commits + more,
                        "commits_truncated": bool(cursor),
                    }
                )
            results.append(activity)

        log.info(
            "github.batch_fetched",
            repos=len(chunk),
            not_found=sum(1 for r in results[-len(chunk) :] if r.status is FetchStatus.NOT_FOUND),
            points_spent=client.points_spent,
            remaining=(client.last_rate_limit.remaining if client.last_rate_limit else None),
        )
    return results
