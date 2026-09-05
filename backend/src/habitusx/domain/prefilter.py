"""Compile the registry into coarse prefilter regexes for the warehouse query.

Reading every commit message into Python would move gigabytes a day. Instead the SQL
keeps only commits that *might* match a registry signal, plus reverts and the within-repo
baseline, and the precise attribution engine runs on that much smaller set in Python.

The prefilter must therefore be a superset of what the engine would match, never a
subset. It is built from the same registry, so adding an agent to ``agents.yaml``
automatically widens the SQL filter.

BigQuery uses RE2. RE2 has no lookaround and no backreferences; :func:`assert_re2_safe`
rejects patterns that use them so the failure happens in a unit test, not in production.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from habitusx.domain.attribution import AgentStatus, Registry, SignalType

# Constructs Python's re accepts that RE2 does not.
_RE2_UNSUPPORTED = re.compile(r"\(\?<?[=!]|\\[1-9]|\(\?\(")

# Matches nothing, in both Python and RE2. Used when a filter has no patterns.
NEVER_MATCHES = r"[^\s\S]"


@dataclass(frozen=True, slots=True)
class Prefilter:
    """Regexes applied in SQL to narrow the candidate set. All case-insensitive."""

    message: str
    author_email: str
    author_name: str
    pusher_login: str


def assert_re2_safe(pattern: str) -> None:
    """Raise ``ValueError`` if ``pattern`` uses syntax RE2 does not support."""
    found = _RE2_UNSUPPORTED.search(pattern)
    if found:
        msg = f"pattern {pattern!r} uses {found.group(0)!r}, which BigQuery's RE2 does not support"
        raise ValueError(msg)


def strip_anchors(pattern: str) -> str:
    """Remove leading ``^`` and trailing ``$`` so a field pattern can sit inside a wider one."""
    inner = pattern
    if inner.startswith("^"):
        inner = inner[1:]
    if inner.endswith("$") and not inner.endswith(r"\$"):
        inner = inner[:-1]
    return inner


def _alternation(parts: list[str], *, multiline: bool = False) -> str:
    """Join patterns into one case-insensitive alternation.

    Flags go once at the very start: Python rejects inline flags anywhere else, and RE2
    accepts them there too, so the result compiles identically in both engines.
    """
    if not parts:
        return NEVER_MATCHES
    flags = "(?im)" if multiline else "(?i)"
    return flags + "(?:" + "|".join(f"(?:{p})" for p in parts) + ")"


def compile_prefilter(registry: Registry) -> Prefilter:
    """Build the SQL prefilter from every non-deprecated signal in ``registry``.

    Raises:
        ValueError: if any signal pattern is not RE2-compatible.
    """
    message: list[str] = []
    author_email: list[str] = []
    author_name: list[str] = []
    pusher_login: list[str] = []

    for agent in registry.agents:
        if agent.status is AgentStatus.DEPRECATED:
            continue
        for signal in agent.signals:
            assert_re2_safe(signal.pattern)
            inner = strip_anchors(signal.pattern)
            match signal.type:
                case (
                    SignalType.TRAILER_EMAIL | SignalType.TRAILER_NAME | SignalType.TRAILER_PRESENT
                ):
                    key = re.escape(signal.trailer_key or "")
                    # Trailer key at line start (multiline mode), rest of that line, marker.
                    message.append(rf"^{key}\s*:[^\n]*{inner}")
                case SignalType.MESSAGE:
                    message.append(signal.pattern)
                case SignalType.AUTHOR_EMAIL:
                    author_email.append(signal.pattern)
                case SignalType.AUTHOR_NAME:
                    author_name.append(signal.pattern)
                case SignalType.AUTHOR_LOGIN:
                    # Push events carry no per-commit login; the pushing actor is the proxy.
                    pusher_login.append(signal.pattern)
                case SignalType.PR_BODY:
                    # Not observable in push events; handled by the pull request ingest.
                    continue

    return Prefilter(
        message=_alternation(message, multiline=True),
        author_email=_alternation(author_email),
        author_name=_alternation(author_name),
        pusher_login=_alternation(pusher_login),
    )
