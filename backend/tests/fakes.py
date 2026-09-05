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
