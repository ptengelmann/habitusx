"""The row the ingest pipeline produces for every commit it keeps.

One :class:`CommitObservation` per commit. Identities are hashed on the way in; the only
raw identity strings retained are the matched fragments in attribution evidence, which by
construction are agent markers (bot logins, vendor no-reply addresses), not people.
"""

from __future__ import annotations

import hashlib
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field

from habitusx.domain.attribution import Attribution
from habitusx.domain.commits import RepoFullName, Sha
from habitusx.domain.reverts import RevertInfo

METHODOLOGY_VERSION = "ingest-v1"
"""Bump when the SQL, the prefilter construction or the row semantics change."""


def hash_identity(value: str | None) -> str | None:
    """Stable, non-reversible identifier for an email, name or login. ``None`` stays ``None``."""
    if not value:
        return None
    return hashlib.sha256(value.strip().lower().encode("utf-8")).hexdigest()[:16]


class CommitObservation(BaseModel):
    """Everything the outcomes pipeline needs to know about one commit on one day."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    # Provenance
    day: date
    methodology_version: str = METHODOLOGY_VERSION
    registry_version: int

    # Where and when
    event_id: str
    repo: RepoFullName
    sha: Sha
    pushed_at: datetime
    is_distinct: bool = Field(description="False when the push re-sent a commit already seen.")
    push_size: int | None = Field(description="Commits in the push; the archive lists at most 20.")

    # What
    subject: str
    message: str
    is_revert: bool
    revert: RevertInfo | None

    # Identities are hashed on ingest and never stored in the clear.
    author_email_hash: str | None
    author_name_hash: str | None
    pusher_login_hash: str | None
    pusher_is_bot: bool

    # Attribution
    attribution: Attribution | None
    agent_id: str | None = Field(description="Denormalised from attribution for cheap grouping.")
    matched_prefilter: bool = Field(
        description="True if the SQL prefilter flagged this commit; false for baseline rows."
    )

    # Baseline context
    commits_in_repo_day: int = Field(ge=1)
