"""Revert detection from commit messages.

GitHub and ``git revert`` both produce a recognisable shape::

    Revert "Add retry to fetcher (#123)" (#130)

    This reverts commit 3f2a9c1e....

    Reverts owner/repo#123

The subject carries the original subject in quotes, the body carries the reverted SHA
and, for pull request reverts, the PR reference. ``Reapply "..."`` is the inverse
operation and is recognised so a revert-of-a-revert is not counted as a fresh failure.
"""

from __future__ import annotations

import re

from pydantic import BaseModel, ConfigDict

from habitusx.domain.trailers import normalise_message

_SUBJECT = re.compile(
    r"^(?P<verb>Revert|Reapply)\s+\"(?P<subject>.*)\"(?:\s+\(#(?P<own_pr>\d+)\))?\s*$",
    re.DOTALL,
)
_REVERTS_SHA = re.compile(r"This reverts commit (?P<sha>[0-9a-fA-F]{7,40})\b")
_REVERTS_PR = re.compile(r"^Reverts\s+(?:[\w.-]+/[\w.-]+)?#(?P<pr>\d+)\s*$", re.MULTILINE)
_TRAILING_PR = re.compile(r"\(#(?P<pr>\d+)\)\s*$")


class RevertInfo(BaseModel):
    """What a revert (or reapply) commit tells us about the commit it undoes."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    is_reapply: bool
    original_subject: str
    reverted_sha: str | None = None
    original_pr_number: int | None = None
    revert_pr_number: int | None = None


def parse_revert(message: str) -> RevertInfo | None:
    """Return revert details if ``message`` is a revert or reapply commit, else ``None``.

    Never raises for any string input.
    """
    text = normalise_message(message).lstrip()
    if not text:
        return None

    paragraphs = re.split(r"\n\s*\n", text, maxsplit=1)
    subject_block = paragraphs[0].replace("\n", " ").strip()
    body = paragraphs[1] if len(paragraphs) > 1 else ""

    subject_match = _SUBJECT.match(subject_block)
    if subject_match is None:
        return None

    original_subject = subject_match["subject"].strip()

    sha_match = _REVERTS_SHA.search(body)
    reverted_sha = sha_match["sha"].lower() if sha_match else None

    original_pr: int | None = None
    pr_from_body = _REVERTS_PR.search(body)
    if pr_from_body:
        original_pr = int(pr_from_body["pr"])
    else:
        pr_from_subject = _TRAILING_PR.search(original_subject)
        if pr_from_subject:
            original_pr = int(pr_from_subject["pr"])

    own_pr = subject_match["own_pr"]
    return RevertInfo(
        is_reapply=subject_match["verb"] == "Reapply",
        original_subject=original_subject,
        reverted_sha=reverted_sha,
        original_pr_number=original_pr,
        revert_pr_number=int(own_pr) if own_pr else None,
    )
