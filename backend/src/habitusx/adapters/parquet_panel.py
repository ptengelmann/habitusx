"""Parquet schemas and flatteners for panel output: repository snapshots, commits, pulls."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

import pyarrow as pa

from habitusx.adapters.parquet import write_records

if TYPE_CHECKING:
    from collections.abc import Iterable
    from pathlib import Path

    from habitusx.domain.attribution import Attribution
    from habitusx.domain.panel_observations import PanelCommit, PanelPullRequest, RepoSnapshot
    from habitusx.domain.reverts import RevertInfo

_REPO_FIELDS: list[pa.Field[Any]] = [
    pa.field("fetched_on", pa.date32(), nullable=False),
    pa.field("panel_version", pa.int32(), nullable=False),
    pa.field("repo", pa.string(), nullable=False),
    pa.field("cohort", pa.string(), nullable=False),
    pa.field("status", pa.string(), nullable=False),
    pa.field("repo_id", pa.int64()),
    pa.field("primary_language", pa.string()),
    pa.field("is_fork", pa.bool_()),
    pa.field("stargazers", pa.int64()),
    pa.field("default_branch", pa.string()),
    pa.field("commits_total_since", pa.int64()),
    pa.field("commits_truncated", pa.bool_(), nullable=False),
    pa.field("error", pa.string()),
]
REPOS_SCHEMA = pa.schema(_REPO_FIELDS)

_ATTRIBUTION_FIELDS: list[pa.Field[Any]] = [
    pa.field("agent_id", pa.string()),
    pa.field("attribution_confidence", pa.string()),
    pa.field("evidence_json", pa.string()),
]
_REVERT_FIELDS: list[pa.Field[Any]] = [
    pa.field("is_revert", pa.bool_(), nullable=False),
    pa.field("is_reapply", pa.bool_()),
    pa.field("reverted_sha", pa.string()),
    pa.field("original_pr_number", pa.int64()),
    pa.field("revert_pr_number", pa.int64()),
]

_COMMIT_FIELDS: list[pa.Field[Any]] = [
    pa.field("fetched_on", pa.date32(), nullable=False),
    pa.field("panel_version", pa.int32(), nullable=False),
    pa.field("methodology_version", pa.string(), nullable=False),
    pa.field("registry_version", pa.int32(), nullable=False),
    pa.field("repo", pa.string(), nullable=False),
    pa.field("cohort", pa.string(), nullable=False),
    pa.field("sha", pa.string(), nullable=False),
    pa.field("committed_at", pa.timestamp("us", tz="UTC"), nullable=False),
    pa.field("subject", pa.string(), nullable=False),
    pa.field("message", pa.string(), nullable=False),
    pa.field("associated_pr_number", pa.int64()),
    pa.field("author_login_hash", pa.string()),
    pa.field("author_email_hash", pa.string()),
    pa.field("author_name_hash", pa.string()),
    pa.field("author_is_bot", pa.bool_(), nullable=False),
    *_REVERT_FIELDS,
    *_ATTRIBUTION_FIELDS,
]
COMMITS_SCHEMA = pa.schema(_COMMIT_FIELDS)

_PULL_FIELDS: list[pa.Field[Any]] = [
    pa.field("fetched_on", pa.date32(), nullable=False),
    pa.field("panel_version", pa.int32(), nullable=False),
    pa.field("methodology_version", pa.string(), nullable=False),
    pa.field("registry_version", pa.int32(), nullable=False),
    pa.field("repo", pa.string(), nullable=False),
    pa.field("cohort", pa.string(), nullable=False),
    pa.field("number", pa.int64(), nullable=False),
    pa.field("title", pa.string(), nullable=False),
    pa.field("state", pa.string(), nullable=False),
    pa.field("created_at", pa.timestamp("us", tz="UTC"), nullable=False),
    pa.field("closed_at", pa.timestamp("us", tz="UTC")),
    pa.field("merged_at", pa.timestamp("us", tz="UTC")),
    pa.field("merged", pa.bool_(), nullable=False),
    pa.field("merge_commit_sha", pa.string()),
    pa.field("author_login_hash", pa.string()),
    pa.field("author_is_bot", pa.bool_(), nullable=False),
    pa.field("additions", pa.int64()),
    pa.field("deletions", pa.int64()),
    pa.field("changed_files", pa.int64()),
    pa.field("review_count", pa.int32(), nullable=False),
    pa.field("comment_count", pa.int32(), nullable=False),
    pa.field("review_thread_count", pa.int32(), nullable=False),
    *_REVERT_FIELDS,
    *_ATTRIBUTION_FIELDS,
]
PULLS_SCHEMA = pa.schema(_PULL_FIELDS)


def _attribution_columns(attribution: Attribution | None) -> dict[str, Any]:
    if attribution is None:
        return {"agent_id": None, "attribution_confidence": None, "evidence_json": None}
    return {
        "agent_id": attribution.agent_id,
        "attribution_confidence": attribution.confidence.value,
        "evidence_json": json.dumps(
            [e.model_dump(mode="json") for e in attribution.evidence], sort_keys=True
        ),
    }


def _revert_columns(is_revert: bool, revert: RevertInfo | None) -> dict[str, Any]:
    return {
        "is_revert": is_revert,
        "is_reapply": revert.is_reapply if revert else None,
        "reverted_sha": revert.reverted_sha if revert else None,
        "original_pr_number": revert.original_pr_number if revert else None,
        "revert_pr_number": revert.revert_pr_number if revert else None,
    }


def repo_record(s: RepoSnapshot) -> dict[str, Any]:
    """Flatten a repository snapshot."""
    return {
        "fetched_on": s.fetched_on,
        "panel_version": s.panel_version,
        "repo": s.repo,
        "cohort": s.cohort.value,
        "status": s.status.value,
        "repo_id": s.repo_id,
        "primary_language": s.primary_language,
        "is_fork": s.is_fork,
        "stargazers": s.stargazers,
        "default_branch": s.default_branch,
        "commits_total_since": s.commits_total_since,
        "commits_truncated": s.commits_truncated,
        "error": s.error,
    }


def commit_record(c: PanelCommit) -> dict[str, Any]:
    """Flatten a panel commit."""
    return {
        "fetched_on": c.fetched_on,
        "panel_version": c.panel_version,
        "methodology_version": c.methodology_version,
        "registry_version": c.registry_version,
        "repo": c.repo,
        "cohort": c.cohort.value,
        "sha": c.sha,
        "committed_at": c.committed_at,
        "subject": c.subject,
        "message": c.message,
        "associated_pr_number": c.associated_pr_number,
        "author_login_hash": c.author_login_hash,
        "author_email_hash": c.author_email_hash,
        "author_name_hash": c.author_name_hash,
        "author_is_bot": c.author_is_bot,
        **_revert_columns(c.is_revert, c.revert),
        **_attribution_columns(c.attribution),
    }


def pull_record(p: PanelPullRequest) -> dict[str, Any]:
    """Flatten a panel pull request."""
    return {
        "fetched_on": p.fetched_on,
        "panel_version": p.panel_version,
        "methodology_version": p.methodology_version,
        "registry_version": p.registry_version,
        "repo": p.repo,
        "cohort": p.cohort.value,
        "number": p.number,
        "title": p.title,
        "state": p.state,
        "created_at": p.created_at,
        "closed_at": p.closed_at,
        "merged_at": p.merged_at,
        "merged": p.merged,
        "merge_commit_sha": p.merge_commit_sha,
        "author_login_hash": p.author_login_hash,
        "author_is_bot": p.author_is_bot,
        "additions": p.additions,
        "deletions": p.deletions,
        "changed_files": p.changed_files,
        "review_count": p.review_count,
        "comment_count": p.comment_count,
        "review_thread_count": p.review_thread_count,
        **_revert_columns(p.is_revert, p.revert),
        **_attribution_columns(p.attribution),
    }


def write_repos(snapshots: Iterable[RepoSnapshot], path: Path) -> int:
    """Write repository snapshots to Parquet."""
    return write_records((repo_record(s) for s in snapshots), REPOS_SCHEMA, path)


def write_commits(commits: Iterable[PanelCommit], path: Path) -> int:
    """Write panel commits to Parquet."""
    return write_records((commit_record(c) for c in commits), COMMITS_SCHEMA, path)


def write_pulls(pulls: Iterable[PanelPullRequest], path: Path) -> int:
    """Write panel pull requests to Parquet."""
    return write_records((pull_record(p) for p in pulls), PULLS_SCHEMA, path)
