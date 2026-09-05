"""Git trailer parsing.

Trailers are the ``Key: value`` lines in the final paragraph of a commit message, such as
``Co-Authored-By: Claude <noreply@anthropic.com>`` or ``Signed-off-by: ...``. They are the
most reliable attribution signal AI coding agents leave behind, so this parser follows
``git interpret-trailers`` semantics closely rather than pattern-matching anywhere in the
message.

Rules implemented:

* Only the last paragraph of the message is considered.
* A single-paragraph message (subject only) has no trailers.
* Every line in the trailer block must be a trailer, a folded continuation line
  (starting with whitespace), or a ``(cherry picked from commit ...)`` note.
* Keys are letters, digits and hyphens; matching on keys is case-insensitive.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_TRAILER_LINE = re.compile(r"^(?P<key>[A-Za-z0-9][A-Za-z0-9-]*)\s*:\s*(?P<value>.*)$")
_CHERRY_PICK_LINE = re.compile(r"^\(cherry picked from commit [0-9a-fA-F]{7,64}\)$")
_PERSON = re.compile(r"^\s*(?P<name>.*?)\s*<(?P<email>[^<>]+)>\s*$")


@dataclass(frozen=True, slots=True)
class Trailer:
    """One parsed trailer line."""

    key: str
    value: str


@dataclass(frozen=True, slots=True)
class Person:
    """A ``Name <email>`` value as used by Co-Authored-By and Signed-off-by."""

    name: str
    email: str


def normalise_message(message: str) -> str:
    """Normalise line endings and strip trailing blank lines."""
    return message.replace("\r\n", "\n").replace("\r", "\n").rstrip()


def parse_trailers(message: str) -> tuple[Trailer, ...]:
    """Return the trailers in ``message``, in order, or an empty tuple if there are none.

    Never raises for any string input.
    """
    text = normalise_message(message)
    if not text:
        return ()

    paragraphs = re.split(r"\n\s*\n", text)
    if len(paragraphs) < 2:
        return ()

    block = paragraphs[-1].split("\n")
    trailers: list[Trailer] = []
    for line in block:
        if not line.strip():
            continue
        if line[0].isspace():
            # Folded continuation of the previous trailer value.
            if not trailers:
                return ()
            previous = trailers[-1]
            trailers[-1] = Trailer(previous.key, f"{previous.value} {line.strip()}".strip())
            continue
        if _CHERRY_PICK_LINE.match(line):
            continue
        match = _TRAILER_LINE.match(line)
        if match is None:
            # A non-trailer line means this paragraph is prose, not a trailer block.
            return ()
        trailers.append(Trailer(match["key"], match["value"].strip()))
    return tuple(trailers)


def find_trailers(message: str, key: str) -> tuple[str, ...]:
    """Return the values of every trailer whose key equals ``key``, case-insensitively."""
    wanted = key.lower()
    return tuple(t.value for t in parse_trailers(message) if t.key.lower() == wanted)


def parse_person(value: str) -> Person | None:
    """Parse ``Name <email>`` into its parts, or return ``None`` if the shape does not fit."""
    match = _PERSON.match(value)
    if match is None:
        return None
    return Person(name=match["name"], email=match["email"].strip())
