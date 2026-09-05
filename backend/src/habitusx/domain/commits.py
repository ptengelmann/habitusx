"""Commit and repository value objects shared across the pipeline."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from habitusx.domain.trailers import normalise_message

# Pattern is checked before to_lower runs, so it must accept either case.
Sha = Annotated[str, StringConstraints(pattern=r"^[0-9a-fA-F]{40}$", to_lower=True)]
RepoFullName = Annotated[
    str,
    StringConstraints(pattern=r"^[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?/[A-Za-z0-9._-]+$"),
]

_SUBJECT_SPLIT = re.compile(r"\n\s*\n|\n")


class Commit(BaseModel):
    """A single commit as observed in a push event.

    Only the fields the outcomes pipeline needs are modelled. ``author_login`` is the
    GitHub login when the archive exposes it, otherwise ``None``; email and name come
    from the git author identity and are always present in the archive.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    sha: Sha
    repo: RepoFullName
    message: str
    author_name: str | None = None
    author_email: str | None = None
    author_login: str | None = None
    committed_at: datetime | None = None
    pushed_at: datetime | None = Field(
        default=None,
        description="When the push event carrying this commit was recorded.",
    )

    @property
    def subject(self) -> str:
        """The first line of the message, with surrounding whitespace removed."""
        text = normalise_message(self.message).lstrip()
        if not text:
            return ""
        return _SUBJECT_SPLIT.split(text, maxsplit=1)[0].strip()
