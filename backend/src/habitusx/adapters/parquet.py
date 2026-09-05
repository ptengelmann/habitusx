"""Write and read :class:`CommitObservation` rows as Parquet.

Parquet is the landing format between ingest and the serving database: columnar,
compressed, typed, readable by every warehouse and by pandas/polars. The schema is
explicit so a change in the model is a deliberate change here too.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

import pyarrow as pa
import pyarrow.parquet as pq

if TYPE_CHECKING:
    from collections.abc import Iterable
    from pathlib import Path

    from habitusx.domain.observations import CommitObservation

_FIELDS: list[pa.Field[Any]] = [
    pa.field("day", pa.date32(), nullable=False),
    pa.field("methodology_version", pa.string(), nullable=False),
    pa.field("registry_version", pa.int32(), nullable=False),
    pa.field("event_id", pa.string(), nullable=False),
    pa.field("repo", pa.string(), nullable=False),
    pa.field("sha", pa.string(), nullable=False),
    pa.field("pushed_at", pa.timestamp("us", tz="UTC"), nullable=False),
    pa.field("is_distinct", pa.bool_(), nullable=False),
    pa.field("push_size", pa.int32()),
    pa.field("subject", pa.string(), nullable=False),
    pa.field("message", pa.string(), nullable=False),
    pa.field("is_revert", pa.bool_(), nullable=False),
    pa.field("is_reapply", pa.bool_()),
    pa.field("reverted_sha", pa.string()),
    pa.field("original_pr_number", pa.int64()),
    pa.field("revert_pr_number", pa.int64()),
    pa.field("author_email_hash", pa.string()),
    pa.field("author_name_hash", pa.string()),
    pa.field("pusher_login_hash", pa.string()),
    pa.field("pusher_is_bot", pa.bool_(), nullable=False),
    pa.field("agent_id", pa.string()),
    pa.field("attribution_confidence", pa.string()),
    pa.field("evidence_json", pa.string()),
    pa.field("matched_prefilter", pa.bool_(), nullable=False),
    pa.field("commits_in_repo_day", pa.int32(), nullable=False),
]
SCHEMA = pa.schema(_FIELDS)


def to_record(obs: CommitObservation) -> dict[str, Any]:
    """Flatten an observation into one Parquet row."""
    revert = obs.revert
    attribution = obs.attribution
    return {
        "day": obs.day,
        "methodology_version": obs.methodology_version,
        "registry_version": obs.registry_version,
        "event_id": obs.event_id,
        "repo": obs.repo,
        "sha": obs.sha,
        "pushed_at": obs.pushed_at,
        "is_distinct": obs.is_distinct,
        "push_size": obs.push_size,
        "subject": obs.subject,
        "message": obs.message,
        "is_revert": obs.is_revert,
        "is_reapply": revert.is_reapply if revert else None,
        "reverted_sha": revert.reverted_sha if revert else None,
        "original_pr_number": revert.original_pr_number if revert else None,
        "revert_pr_number": revert.revert_pr_number if revert else None,
        "author_email_hash": obs.author_email_hash,
        "author_name_hash": obs.author_name_hash,
        "pusher_login_hash": obs.pusher_login_hash,
        "pusher_is_bot": obs.pusher_is_bot,
        "agent_id": obs.agent_id,
        "attribution_confidence": attribution.confidence.value if attribution else None,
        "evidence_json": (
            json.dumps([e.model_dump(mode="json") for e in attribution.evidence], sort_keys=True)
            if attribution
            else None
        ),
        "matched_prefilter": obs.matched_prefilter,
        "commits_in_repo_day": obs.commits_in_repo_day,
    }


def write_records(records: Iterable[dict[str, Any]], schema: pa.Schema, path: Path) -> int:
    """Write flat records to ``path`` as one zstd Parquet file with ``schema``. Returns rows."""
    table = pa.Table.from_pylist(list(records), schema=schema)
    path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(table, path, compression="zstd")
    return int(table.num_rows)


def read_table(path: Path, schema: pa.Schema | None = None) -> list[dict[str, Any]]:
    """Read a Parquet file back into plain dicts, optionally validating against ``schema``."""
    records: list[dict[str, Any]] = pq.read_table(path, schema=schema).to_pylist()
    return records


def write_observations(observations: Iterable[CommitObservation], path: Path) -> int:
    """Write census observations to ``path``. Returns the row count."""
    return write_records((to_record(o) for o in observations), SCHEMA, path)


def read_records(path: Path) -> list[dict[str, Any]]:
    """Read a file written by :func:`write_observations` back into plain dicts."""
    return read_table(path, SCHEMA)
