"""Rows produced by a panel fetch.

One snapshot per repository, one row per commit, one row per pull request. Identities are
hashed; only agent markers survive in evidence.
"""

from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from habitusx.domain.attribution import Attribution
from habitusx.domain.commits import RepoFullName, Sha
from habitusx.domain.panel import Cohort
from habitusx.domain.reverts import RevertInfo

PANEL_METHODOLOGY_VERSION = "panel-v1"
"""Bump when the GraphQL query, the parsing or the row semantics change."""


class FetchStatus(StrEnum):
    """What happened when we asked GitHub about a repository."""

    OK = "ok"
    NOT_FOUND = "not_found"
    """Deleted, made private, or renamed. Counted as attrition."""

    EMPTY = "empty"
    """Exists but has no default branch (never pushed)."""

    ERROR = "error"


class RepoSnapshot(BaseModel):
    """Repository metadata as of one fetch. Also the attrition record."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    fetched_on: date
    panel_version: int
    repo: RepoFullName
    cohort: Cohort
    status: FetchStatus
    repo_id: int | None = Field(default=None, description="GitHub databaseId; survives renames.")
    primary_language: str | None = None
    is_fork: bool | None = None
    stargazers: int | None = None
    default_branch: str | None = None
    commits_total_since: int | None = Field(
        default=None, description="History count since the watermark, before any truncation."
    )
    commits_truncated: bool = False
    error: str | None = None


class PanelCommit(BaseModel):
    """One commit on the default branch since the previous fetch."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    fetched_on: date
    panel_version: int
    methodology_version: str = PANEL_METHODOLOGY_VERSION
    registry_version: int

    repo: RepoFullName
    cohort: Cohort
    sha: Sha
    committed_at: datetime
    subject: str
    message: str
    associated_pr_number: int | None

    author_login_hash: str | None
    author_email_hash: str | None
    author_name_hash: str | None
    author_is_bot: bool

    is_revert: bool
    revert: RevertInfo | None
    attribution: Attribution | None
    agent_id: str | None


class PanelPullRequest(BaseModel):
    """One pull request updated since the previous fetch, with its outcome so far."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    fetched_on: date
    panel_version: int
    methodology_version: str = PANEL_METHODOLOGY_VERSION
    registry_version: int

    repo: RepoFullName
    cohort: Cohort
    number: int
    title: str
    state: str = Field(description="OPEN, CLOSED or MERGED as reported by GitHub.")
    created_at: datetime
    closed_at: datetime | None
    merged_at: datetime | None
    merged: bool
    merge_commit_sha: Sha | None

    author_login_hash: str | None
    author_is_bot: bool

    additions: int | None
    deletions: int | None
    changed_files: int | None
    review_count: int
    comment_count: int
    review_thread_count: int

    is_revert: bool
    revert: RevertInfo | None
    attribution: Attribution | None
    agent_id: str | None
