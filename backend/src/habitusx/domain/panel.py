"""Panel membership: which repositories we follow, and why.

Since October 2025 the full population of public GitHub activity is no longer observable
(ADR 0006), so the ongoing index measures a **panel**: a deterministic sample of
repositories fetched daily through the GitHub API.

Two cohorts:

* ``treated``: repositories with at least one AI-attributed commit in the historical
  census (Source A). This is where outcomes of AI-written code can be observed at volume.
* ``control``: a hash sample of repositories active on a recent day, regardless of AI use.
  This anchors baselines and lets adoption itself be estimated.

Sampling is by a stable hash of the repository name, so membership is reproducible from
the panel definition alone and independent of the order repositories were discovered in.
"""

from __future__ import annotations

import hashlib
from datetime import date
from enum import StrEnum
from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict, Field, model_validator

from habitusx.domain.commits import RepoFullName

if TYPE_CHECKING:
    from collections.abc import Iterable

SAMPLE_SPACE = 10_000
"""Sample keys are integers in ``[0, SAMPLE_SPACE)``; a rate of 0.0123 keeps keys below 123."""


class Cohort(StrEnum):
    """Why a repository is in the panel."""

    TREATED = "treated"
    CONTROL = "control"


def sample_key(repo: str) -> int:
    """Stable integer in ``[0, SAMPLE_SPACE)`` derived from the lower-cased repository name."""
    digest = hashlib.sha256(repo.strip().lower().encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big") % SAMPLE_SPACE


def in_sample(repo: str, rate: float) -> bool:
    """True if ``repo`` falls inside a sample of the given rate (0.0 to 1.0)."""
    if not 0.0 <= rate <= 1.0:
        msg = f"rate must be between 0 and 1, got {rate}"
        raise ValueError(msg)
    return sample_key(repo) < round(rate * SAMPLE_SPACE)


class PanelMember(BaseModel):
    """One repository in the panel."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    repo: RepoFullName
    cohort: Cohort
    added_on: date
    source: str = Field(description="Origin, e.g. 'source_a' or 'archive_active:2026-08-25'.")
    sample_key: int = Field(ge=0, lt=SAMPLE_SPACE)


class Panel(BaseModel):
    """A versioned panel definition. Immutable once written; changes make a new version."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    version: int = Field(ge=1)
    created_on: date
    treated_rate: float = Field(ge=0.0, le=1.0)
    control_rate: float = Field(ge=0.0, le=1.0)
    members: tuple[PanelMember, ...]

    @model_validator(mode="after")
    def _unique_repos(self) -> Panel:
        seen: set[str] = set()
        for member in self.members:
            key = member.repo.lower()
            if key in seen:
                msg = f"repository {member.repo!r} appears more than once in the panel"
                raise ValueError(msg)
            seen.add(key)
        return self

    def by_cohort(self, cohort: Cohort) -> tuple[PanelMember, ...]:
        """Members of one cohort, in panel order."""
        return tuple(m for m in self.members if m.cohort is cohort)

    @property
    def repos(self) -> tuple[str, ...]:
        """Every repository name, in panel order."""
        return tuple(m.repo for m in self.members)


def _dedupe_case_insensitive(repos: Iterable[str]) -> list[str]:
    """Keep one spelling per repository (the lexicographically smallest), sorted."""
    chosen: dict[str, str] = {}
    for repo in repos:
        key = repo.lower()
        if key not in chosen or repo < chosen[key]:
            chosen[key] = repo
    return sorted(chosen.values(), key=str.lower)


def build_panel(
    *,
    version: int,
    created_on: date,
    treated_candidates: Iterable[str],
    control_candidates: Iterable[str],
    treated_rate: float,
    control_rate: float,
    control_source: str,
) -> Panel:
    """Assemble a panel from candidate lists using hash sampling.

    Treated candidates are sampled first. A repository that qualifies for both cohorts is
    kept as treated only, so cohorts never overlap. Output order is deterministic:
    treated then control, each sorted by name.
    """
    # GitHub repository names are case-insensitive; the archive records whichever spelling
    # the event carried, so the same repository can appear as "Owner/Repo" and "owner/repo".
    treated = _dedupe_case_insensitive(r for r in treated_candidates if in_sample(r, treated_rate))
    treated_keys = {r.lower() for r in treated}
    control = _dedupe_case_insensitive(
        r
        for r in control_candidates
        if r.lower() not in treated_keys and in_sample(r, control_rate)
    )
    members = [
        PanelMember(
            repo=r,
            cohort=Cohort.TREATED,
            added_on=created_on,
            source="source_a",
            sample_key=sample_key(r),
        )
        for r in treated
    ] + [
        PanelMember(
            repo=r,
            cohort=Cohort.CONTROL,
            added_on=created_on,
            source=control_source,
            sample_key=sample_key(r),
        )
        for r in control
    ]
    return Panel(
        version=version,
        created_on=created_on,
        treated_rate=treated_rate,
        control_rate=control_rate,
        members=tuple(members),
    )
