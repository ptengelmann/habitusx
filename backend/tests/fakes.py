"""In-memory stand-ins for the BigQuery client, shared by adapter, service and CLI tests."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

SHA_A = "a" * 40
SHA_B = "b" * 40
SHA_C = "c" * 40
SHA_D = "d" * 40
PUSHED_AT = datetime(2025, 9, 1, 12, 0, tzinfo=UTC)


def fake_job_config(dry_run: bool, maximum_bytes_billed: int | None, params: Any) -> Any:
    """Cheap replacement for ``bigquery.QueryJobConfig`` that records what it was given."""
    return SimpleNamespace(
        dry_run=dry_run, maximum_bytes_billed=maximum_bytes_billed, params=dict(params)
    )


@dataclass
class FakeJob:
    total_bytes_processed: int | None
    total_bytes_billed: int | None
    slot_millis: int | None
    job_id: str | None
    rows: list[dict[str, Any]] = field(default_factory=list)

    def result(self) -> Iterator[dict[str, Any]]:
        return iter(self.rows)


@dataclass
class FakeClient:
    """Returns ``estimate_bytes`` on dry runs and ``rows`` on real runs; records every call."""

    estimate_bytes: int
    rows: list[dict[str, Any]] = field(default_factory=list)
    billed_bytes: int | None = None
    calls: list[dict[str, Any]] = field(default_factory=list)

    def query(self, query: str, *, job_config: Any = None, location: str | None = None) -> FakeJob:
        self.calls.append({"sql": query, "job_config": job_config, "location": location})
        if job_config is not None and job_config.dry_run:
            return FakeJob(self.estimate_bytes, None, None, None)
        return FakeJob(
            total_bytes_processed=self.estimate_bytes,
            total_bytes_billed=self.billed_bytes
            if self.billed_bytes is not None
            else self.estimate_bytes,
            slot_millis=1234,
            job_id="job-fake-1",
            rows=self.rows,
        )


def warehouse_row(**overrides: Any) -> dict[str, Any]:
    """A row shaped like ``commits_for_day.sql`` output, with sensible defaults."""
    row: dict[str, Any] = {
        "event_id": "1001",
        "repo": "octo/repo",
        "pusher_login": "octocat",
        "pushed_at": PUSHED_AT,
        "push_size": 1,
        "sha": SHA_A,
        "message": "Plain human commit",
        "author_name": "Octo Cat",
        "author_email": "octo@example.com",
        "is_distinct": True,
        "message_hit": False,
        "author_email_hit": False,
        "author_name_hit": False,
        "pusher_login_hit": False,
        "revert_hit": False,
        "commits_in_repo_day": 4,
    }
    row.update(overrides)
    return row


def sample_rows() -> list[dict[str, Any]]:
    """One attributed commit, one revert, one baseline commit, one invalid row."""
    return [
        warehouse_row(
            sha=SHA_A,
            message="Add retry\n\nCo-Authored-By: Claude <noreply@anthropic.com>\n",
            message_hit=True,
        ),
        warehouse_row(
            event_id="1002",
            sha=SHA_B,
            message=f'Revert "Add retry (#12)" (#15)\n\nThis reverts commit {SHA_A}.\n',
            revert_hit=True,
            pusher_login="copilot-swe-agent[bot]",
            pusher_login_hit=True,
        ),
        warehouse_row(event_id="1003", sha=SHA_C, message="Tidy imports"),
        warehouse_row(event_id="1004", sha="not-a-sha", message="Broken row"),
    ]


# ---------------------------------------------------------------------------------------
# GitHub GraphQL fakes
# ---------------------------------------------------------------------------------------

CLAUDE_TRAILER_MSG = "Add retry\n\nCo-Authored-By: Claude <noreply@anthropic.com>\n"


def gql_commit(
    sha: str = SHA_A,
    message: str = "Plain commit",
    *,
    login: str | None = "octocat",
    is_bot: bool = False,
    email: str | None = "octo@example.com",
    pr_number: int | None = None,
    committed_at: str = "2026-09-02T10:00:00Z",
) -> dict[str, Any]:
    """One node of repository.defaultBranchRef.target.history.nodes."""
    return {
        "oid": sha,
        "committedDate": committed_at,
        "messageHeadline": message.splitlines()[0] if message else "",
        "message": message,
        "author": {
            "name": "Octo Cat",
            "email": email,
            "user": {"login": login, "__typename": "Bot" if is_bot else "User"} if login else None,
        },
        "associatedPullRequests": {"nodes": [{"number": pr_number}] if pr_number else []},
    }


def gql_pull(
    number: int = 7,
    title: str = "Add retry",
    *,
    body: str = "",
    login: str | None = "octocat",
    is_bot: bool = False,
    merged: bool = True,
    updated_at: str = "2026-09-02T12:00:00Z",
    merge_sha: str | None = SHA_B,
) -> dict[str, Any]:
    """One node of repository.pullRequests.nodes."""
    return {
        "number": number,
        "title": title,
        "body": body,
        "state": "MERGED" if merged else "OPEN",
        "createdAt": "2026-09-01T09:00:00Z",
        "closedAt": "2026-09-02T12:00:00Z" if merged else None,
        "mergedAt": "2026-09-02T12:00:00Z" if merged else None,
        "merged": merged,
        "updatedAt": updated_at,
        "author": {"login": login, "__typename": "Bot" if is_bot else "User"} if login else None,
        "additions": 10,
        "deletions": 2,
        "changedFiles": 1,
        "reviews": {"totalCount": 1},
        "comments": {"totalCount": 2},
        "reviewThreads": {"totalCount": 0},
        "mergeCommit": {"oid": merge_sha} if merge_sha else None,
    }


def gql_repo(
    name_with_owner: str = "octo/repo",
    *,
    commits: list[dict[str, Any]] | None = None,
    pulls: list[dict[str, Any]] | None = None,
    has_next: bool = False,
    cursor: str | None = None,
    total: int | None = None,
    no_branch: bool = False,
    language: str | None = "Python",
) -> dict[str, Any]:
    """One repository alias payload, shaped like the real API."""
    commits = commits if commits is not None else []
    node: dict[str, Any] = {
        "nameWithOwner": name_with_owner,
        "databaseId": 12345,
        "isFork": False,
        "stargazerCount": 42,
        "primaryLanguage": {"name": language} if language else None,
        "pullRequests": {"totalCount": len(pulls or []), "nodes": pulls or []},
    }
    if no_branch:
        node["defaultBranchRef"] = None
    else:
        node["defaultBranchRef"] = {
            "name": "main",
            "target": {
                "history": {
                    "totalCount": total if total is not None else len(commits),
                    "pageInfo": {"hasNextPage": has_next, "endCursor": cursor},
                    "nodes": commits,
                }
            },
        }
    return node


def gql_response(
    aliases: dict[str, dict[str, Any] | None],
    *,
    cost: int = 3,
    remaining: int = 4990,
    reset_at: str = "2026-09-05T13:00:00Z",
    errors: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """A full GraphQL body. Aliases mapped to None become NOT_FOUND errors."""
    data: dict[str, Any] = {
        "rateLimit": {"cost": cost, "remaining": remaining, "resetAt": reset_at}
    }
    errs = list(errors or [])
    for alias, node in aliases.items():
        data[alias] = node
        if node is None:
            errs.append(
                {
                    "type": "NOT_FOUND",
                    "path": [alias],
                    "message": "Could not resolve to a Repository.",
                }
            )
    body: dict[str, Any] = {"data": data}
    if errs:
        body["errors"] = errs
    return body


@dataclass
class FakeTransport:
    """Returns canned bodies in order; records every (query, variables) pair."""

    bodies: list[dict[str, Any]]
    calls: list[tuple[str, dict[str, Any]]] = field(default_factory=list)

    def post(self, query: str, variables: dict[str, Any]) -> dict[str, Any]:
        self.calls.append((query, variables))
        if not self.bodies:
            msg = "FakeTransport has no more responses"
            raise AssertionError(msg)
        return self.bodies.pop(0)
