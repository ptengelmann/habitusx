"""Ingest one UTC day of GitHub Archive into attributed commit observations.

    registry ──> prefilter ──> SQL ──> BigQuery ──> rows ──> engine + revert parser
                                                              │
                                                              ▼
                                            observations/day=YYYY-MM-DD/commits.parquet
                                            observations/day=YYYY-MM-DD/manifest.json

The manifest records everything needed to reproduce or audit the file: registry version,
methodology version, SQL hash, bytes billed, and counts by agent.
"""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from pydantic import ValidationError

from habitusx import __version__
from habitusx.adapters.bigquery.queries import commits_for_day
from habitusx.adapters.parquet import write_observations
from habitusx.domain.attribution import AttributionEngine, AttributionInput, Registry
from habitusx.domain.commits import Commit
from habitusx.domain.observations import METHODOLOGY_VERSION, CommitObservation, hash_identity
from habitusx.domain.prefilter import compile_prefilter
from habitusx.domain.reverts import parse_revert
from habitusx.logging import get_logger

if TYPE_CHECKING:
    from collections.abc import Mapping
    from datetime import date
    from pathlib import Path

    from habitusx.adapters.bigquery.gateway import BigQueryGateway, QueryStats

log = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class IngestSummary:
    """What one day's ingest produced."""

    day: date
    rows_total: int
    rows_attributed: int
    rows_reverts: int
    rows_baseline: int
    rows_skipped_invalid: int
    by_agent: dict[str, int]
    stats: QueryStats
    output_path: Path
    manifest_path: Path


def output_dir(base: Path, day: date) -> Path:
    """Hive-style partition directory for ``day`` under ``base``."""
    return base / "observations" / f"day={day.isoformat()}"


def estimate_day(day: date, *, registry: Registry, gateway: BigQueryGateway) -> int:
    """Bytes the day's extraction would process. Spends nothing."""
    return gateway.estimate(commits_for_day(day, compile_prefilter(registry)))


def build_observation(
    row: Mapping[str, Any],
    *,
    day: date,
    engine: AttributionEngine,
    registry_version: int,
) -> CommitObservation | None:
    """Turn one warehouse row into an observation, or ``None`` if the row is malformed.

    Malformed means a SHA or repository name that fails validation. Those are counted and
    skipped rather than failing the whole day.
    """
    try:
        commit = Commit(
            sha=row["sha"],
            repo=row["repo"],
            message=row["message"],
            author_name=row.get("author_name"),
            author_email=row.get("author_email"),
            pushed_at=row["pushed_at"],
        )
    except ValidationError as exc:
        log.warning(
            "ingest.skip_invalid_row", repo=row.get("repo"), sha=row.get("sha"), error=str(exc)
        )
        return None

    pusher_login = row.get("pusher_login")
    attribution = engine.attribute(
        AttributionInput(
            message=commit.message,
            author_email=commit.author_email,
            author_name=commit.author_name,
            author_login=pusher_login,
        )
    )
    revert = parse_revert(commit.message)
    matched = bool(
        row.get("message_hit")
        or row.get("author_email_hit")
        or row.get("author_name_hit")
        or row.get("pusher_login_hit")
    )
    return CommitObservation(
        day=day,
        methodology_version=METHODOLOGY_VERSION,
        registry_version=registry_version,
        event_id=str(row["event_id"]),
        repo=commit.repo,
        sha=commit.sha,
        pushed_at=row["pushed_at"],
        is_distinct=bool(row.get("is_distinct", True)),
        push_size=row.get("push_size"),
        subject=commit.subject[:500],
        message=commit.message,
        is_revert=revert is not None,
        revert=revert,
        author_email_hash=hash_identity(commit.author_email),
        author_name_hash=hash_identity(commit.author_name),
        pusher_login_hash=hash_identity(pusher_login),
        pusher_is_bot=bool(pusher_login and pusher_login.endswith("[bot]")),
        attribution=attribution,
        agent_id=attribution.agent_id if attribution else None,
        matched_prefilter=matched,
        commits_in_repo_day=int(row["commits_in_repo_day"]),
    )


def ingest_day(
    day: date,
    *,
    registry: Registry,
    gateway: BigQueryGateway,
    out_dir: Path,
) -> IngestSummary:
    """Run the full extraction for ``day`` and write Parquet plus a manifest.

    Raises:
        QueryBudgetExceededError: if the dry-run estimate exceeds the gateway ceiling.
    """
    prefilter = compile_prefilter(registry)
    query = commits_for_day(day, prefilter)
    engine = AttributionEngine(registry)

    result = gateway.run(query)

    observations: list[CommitObservation] = []
    skipped = 0
    for row in result.rows:
        obs = build_observation(row, day=day, engine=engine, registry_version=registry.version)
        if obs is None:
            skipped += 1
            continue
        observations.append(obs)

    by_agent = Counter(o.agent_id for o in observations if o.agent_id)
    n_reverts = sum(1 for o in observations if o.is_revert)
    n_attributed = sum(by_agent.values())
    n_baseline = sum(1 for o in observations if not o.matched_prefilter and not o.is_revert)

    target = output_dir(out_dir, day)
    parquet_path = target / "commits.parquet"
    manifest_path = target / "manifest.json"
    write_observations(observations, parquet_path)

    manifest = {
        "day": day.isoformat(),
        "written_at": datetime.now(UTC).isoformat(),
        "habitusx_version": __version__,
        "methodology_version": METHODOLOGY_VERSION,
        "registry_version": registry.version,
        "query": {"name": query.name, "sql_hash": query.sql_hash, "params": query.params},
        "stats": asdict(result.stats),
        "rows": {
            "total": len(observations),
            "attributed": n_attributed,
            "reverts": n_reverts,
            "baseline": n_baseline,
            "skipped_invalid": skipped,
        },
        "by_agent": dict(sorted(by_agent.items())),
        "files": {"commits": parquet_path.name},
    }
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

    log.info(
        "ingest.day_complete",
        day=day.isoformat(),
        rows=len(observations),
        attributed=n_attributed,
        reverts=n_reverts,
        skipped=skipped,
        billed_bytes=result.stats.billed_bytes,
    )
    return IngestSummary(
        day=day,
        rows_total=len(observations),
        rows_attributed=n_attributed,
        rows_reverts=n_reverts,
        rows_baseline=n_baseline,
        rows_skipped_invalid=skipped,
        by_agent=dict(by_agent),
        stats=result.stats,
        output_path=parquet_path,
        manifest_path=manifest_path,
    )
