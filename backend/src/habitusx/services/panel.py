"""The repository panel: build it, fetch it, write it.

build:  census Parquet (treated candidates) + archive active repos (control candidates)
        ──hash sample──> panel_vN.json

fetch:  panel_vN.json ──GitHub GraphQL──> RepoActivity per repo
        ──engine + revert parser──> repos.parquet, commits.parquet, pulls.parquet
                                    + manifest.json   under panel/fetched_on=YYYY-MM-DD/
"""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import TYPE_CHECKING

from pydantic import ValidationError

from habitusx import __version__
from habitusx.adapters.bigquery.queries import active_repos_for_day
from habitusx.adapters.github.activity import (
    RawCommit,
    RawPullRequest,
    RepoActivity,
    fetch_activity,
)
from habitusx.adapters.parquet import read_table
from habitusx.adapters.parquet_panel import write_commits, write_pulls, write_repos
from habitusx.domain.attribution import AttributionEngine, AttributionInput, Registry
from habitusx.domain.observations import hash_identity
from habitusx.domain.panel import Panel, PanelMember, build_panel
from habitusx.domain.panel_observations import (
    PANEL_METHODOLOGY_VERSION,
    FetchStatus,
    PanelCommit,
    PanelPullRequest,
    RepoSnapshot,
)
from habitusx.domain.reverts import parse_revert
from habitusx.errors import HabitusXError
from habitusx.logging import get_logger

if TYPE_CHECKING:
    from collections.abc import Iterable
    from pathlib import Path

    from habitusx.adapters.bigquery.gateway import BigQueryGateway
    from habitusx.adapters.github.client import GitHubGraphQL

log = get_logger(__name__)


class PanelError(HabitusXError):
    """A panel file could not be read or does not validate."""


# ---------------------------------------------------------------------------------------
# Build
# ---------------------------------------------------------------------------------------


def treated_candidates(observations_root: Path) -> set[str]:
    """Repositories with at least one attributed commit across every census day on disk."""
    repos: set[str] = set()
    for parquet in sorted(observations_root.glob("day=*/commits.parquet")):
        for row in read_table(parquet):
            if row.get("agent_id"):
                repos.add(str(row["repo"]))
    return repos


def control_candidates(day: date, *, gateway: BigQueryGateway) -> set[str]:
    """Repositories active on ``day`` according to GitHub Archive."""
    result = gateway.run(active_repos_for_day(day))
    return {str(r["repo"]) for r in result.rows if r.get("repo")}


def save_panel(panel: Panel, path: Path) -> None:
    """Write a panel definition as JSON."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(panel.model_dump_json(indent=2) + "\n", encoding="utf-8")


def load_panel(path: Path) -> Panel:
    """Read and validate a panel definition."""
    try:
        return Panel.model_validate_json(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise PanelError(f"cannot read panel at {path}: {exc}") from exc
    except ValidationError as exc:
        raise PanelError(f"panel at {path} is invalid: {exc}") from exc


def assemble_panel(
    *,
    version: int,
    created_on: date,
    treated: Iterable[str],
    control: Iterable[str],
    treated_rate: float,
    control_rate: float,
    control_source: str,
) -> Panel:
    """Build a panel, surfacing validation problems as :class:`PanelError`."""
    try:
        return build_panel(
            version=version,
            created_on=created_on,
            treated_candidates=treated,
            control_candidates=control,
            treated_rate=treated_rate,
            control_rate=control_rate,
            control_source=control_source,
        )
    except (ValidationError, ValueError) as exc:
        raise PanelError(f"could not build panel: {exc}") from exc


# ---------------------------------------------------------------------------------------
# Fetch
# ---------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class PanelFetchSummary:
    """What one fetch produced."""

    fetched_on: date
    since: datetime
    repos_requested: int
    repos_by_status: dict[str, int]
    commits: int
    commits_attributed: int
    commits_by_agent: dict[str, int]
    reverts: int
    pulls: int
    pulls_attributed: int
    pulls_by_agent: dict[str, int]
    points_spent: int
    requests_made: int
    output_dir: Path


def panel_output_dir(base: Path, fetched_on: date) -> Path:
    """Hive-style partition directory for one fetch."""
    return base / "panel" / f"fetched_on={fetched_on.isoformat()}"


def to_snapshot(
    activity: RepoActivity, member: PanelMember, *, fetched_on: date, panel_version: int
) -> RepoSnapshot:
    """Repository-level record, including attrition status."""
    return RepoSnapshot(
        fetched_on=fetched_on,
        panel_version=panel_version,
        repo=member.repo,
        cohort=member.cohort,
        status=activity.status,
        repo_id=activity.repo_id,
        primary_language=activity.primary_language,
        is_fork=activity.is_fork,
        stargazers=activity.stargazers,
        default_branch=activity.default_branch,
        commits_total_since=activity.commits_total,
        commits_truncated=activity.commits_truncated,
        error=activity.error,
    )


def to_panel_commit(
    raw: RawCommit,
    member: PanelMember,
    *,
    engine: AttributionEngine,
    fetched_on: date,
    panel_version: int,
    registry_version: int,
) -> PanelCommit | None:
    """Attribute one commit. Returns ``None`` if the SHA does not validate."""
    attribution = engine.attribute(
        AttributionInput(
            message=raw.message,
            author_login=raw.author_login,
            author_email=raw.author_email,
            author_name=raw.author_name,
        )
    )
    revert = parse_revert(raw.message)
    try:
        return PanelCommit(
            fetched_on=fetched_on,
            panel_version=panel_version,
            methodology_version=PANEL_METHODOLOGY_VERSION,
            registry_version=registry_version,
            repo=member.repo,
            cohort=member.cohort,
            sha=raw.sha,
            committed_at=raw.committed_at,
            subject=raw.subject[:500],
            message=raw.message,
            associated_pr_number=raw.associated_pr_number,
            author_login_hash=hash_identity(raw.author_login),
            author_email_hash=hash_identity(raw.author_email),
            author_name_hash=hash_identity(raw.author_name),
            author_is_bot=raw.author_is_bot
            or bool(raw.author_login and raw.author_login.endswith("[bot]")),
            is_revert=revert is not None,
            revert=revert,
            attribution=attribution,
            agent_id=attribution.agent_id if attribution else None,
        )
    except ValidationError as exc:
        log.warning("panel.skip_invalid_commit", repo=member.repo, sha=raw.sha, error=str(exc))
        return None


def to_panel_pull(
    raw: RawPullRequest,
    member: PanelMember,
    *,
    engine: AttributionEngine,
    fetched_on: date,
    panel_version: int,
    registry_version: int,
) -> PanelPullRequest:
    """Attribute one pull request from its author, title and body."""
    attribution = engine.attribute(
        AttributionInput(message=raw.title, author_login=raw.author_login, pr_body=raw.body)
    )
    revert = parse_revert(raw.title)
    merge_sha = (
        raw.merge_commit_sha if raw.merge_commit_sha and len(raw.merge_commit_sha) == 40 else None
    )
    return PanelPullRequest(
        fetched_on=fetched_on,
        panel_version=panel_version,
        methodology_version=PANEL_METHODOLOGY_VERSION,
        registry_version=registry_version,
        repo=member.repo,
        cohort=member.cohort,
        number=raw.number,
        title=raw.title[:500],
        state=raw.state,
        created_at=raw.created_at,
        closed_at=raw.closed_at,
        merged_at=raw.merged_at,
        merged=raw.merged,
        merge_commit_sha=merge_sha,
        author_login_hash=hash_identity(raw.author_login),
        author_is_bot=raw.author_is_bot
        or bool(raw.author_login and raw.author_login.endswith("[bot]")),
        additions=raw.additions,
        deletions=raw.deletions,
        changed_files=raw.changed_files,
        review_count=raw.review_count,
        comment_count=raw.comment_count,
        review_thread_count=raw.review_thread_count,
        is_revert=revert is not None,
        revert=revert,
        attribution=attribution,
        agent_id=attribution.agent_id if attribution else None,
    )


def fetch_panel(
    panel: Panel,
    *,
    client: GitHubGraphQL,
    registry: Registry,
    since: datetime,
    fetched_on: date,
    out_dir: Path,
    limit: int | None = None,
    batch_size: int = 5,
) -> PanelFetchSummary:
    """Fetch every panel member's activity since ``since`` and write the three Parquet files.

    ``limit`` caps the number of members fetched, for smoke tests and budget-bounded runs.
    """
    if since.tzinfo is None:
        msg = "since must be timezone-aware (UTC)"
        raise ValueError(msg)
    members = list(panel.members[:limit] if limit else panel.members)
    by_repo = {m.repo: m for m in members}
    engine = AttributionEngine(registry)

    activities = fetch_activity(
        client, [m.repo for m in members], since=since, batch_size=batch_size
    )

    snapshots: list[RepoSnapshot] = []
    commits: list[PanelCommit] = []
    pulls: list[PanelPullRequest] = []
    for activity in activities:
        member = by_repo[activity.repo]
        snapshots.append(
            to_snapshot(activity, member, fetched_on=fetched_on, panel_version=panel.version)
        )
        if activity.status is not FetchStatus.OK:
            continue
        for raw_commit in activity.commits:
            obs = to_panel_commit(
                raw_commit,
                member,
                engine=engine,
                fetched_on=fetched_on,
                panel_version=panel.version,
                registry_version=registry.version,
            )
            if obs is not None:
                commits.append(obs)
        pulls.extend(
            to_panel_pull(
                raw_pull,
                member,
                engine=engine,
                fetched_on=fetched_on,
                panel_version=panel.version,
                registry_version=registry.version,
            )
            for raw_pull in activity.pulls
        )

    target = panel_output_dir(out_dir, fetched_on)
    write_repos(snapshots, target / "repos.parquet")
    write_commits(commits, target / "commits.parquet")
    write_pulls(pulls, target / "pulls.parquet")

    status_counts = Counter(s.status.value for s in snapshots)
    commits_by_agent = Counter(c.agent_id for c in commits if c.agent_id)
    pulls_by_agent = Counter(p.agent_id for p in pulls if p.agent_id)
    summary = PanelFetchSummary(
        fetched_on=fetched_on,
        since=since,
        repos_requested=len(members),
        repos_by_status=dict(sorted(status_counts.items())),
        commits=len(commits),
        commits_attributed=sum(commits_by_agent.values()),
        commits_by_agent=dict(sorted(commits_by_agent.items())),
        reverts=sum(1 for c in commits if c.is_revert),
        pulls=len(pulls),
        pulls_attributed=sum(pulls_by_agent.values()),
        pulls_by_agent=dict(sorted(pulls_by_agent.items())),
        points_spent=client.points_spent,
        requests_made=client.requests_made,
        output_dir=target,
    )

    manifest = {
        "fetched_on": fetched_on.isoformat(),
        "since": since.isoformat(),
        "written_at": datetime.now(UTC).isoformat(),
        "habitusx_version": __version__,
        "methodology_version": PANEL_METHODOLOGY_VERSION,
        "registry_version": registry.version,
        "panel": {
            "version": panel.version,
            "created_on": panel.created_on.isoformat(),
            "members_total": len(panel.members),
            "members_fetched": len(members),
            "treated_rate": panel.treated_rate,
            "control_rate": panel.control_rate,
        },
        "github": {"points_spent": summary.points_spent, "requests": summary.requests_made},
        "repos_by_status": summary.repos_by_status,
        "commits": {
            "total": summary.commits,
            "attributed": summary.commits_attributed,
            "reverts": summary.reverts,
        },
        "commits_by_agent": summary.commits_by_agent,
        "pulls": {"total": summary.pulls, "attributed": summary.pulls_attributed},
        "pulls_by_agent": summary.pulls_by_agent,
        "files": {"repos": "repos.parquet", "commits": "commits.parquet", "pulls": "pulls.parquet"},
    }
    (target / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

    log.info(
        "panel.fetch_complete",
        fetched_on=fetched_on.isoformat(),
        repos=len(members),
        commits=summary.commits,
        pulls=summary.pulls,
        attributed_commits=summary.commits_attributed,
        points=summary.points_spent,
    )
    return summary
