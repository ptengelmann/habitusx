"""Typed exception hierarchy.

Every error raised by HabitusX code derives from :class:`HabitusXError`, so callers can
catch the family without swallowing unrelated failures. Each subclass carries enough
structured context to act on without reading a stack trace.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence


class HabitusXError(Exception):
    """Base class for all HabitusX errors."""


class ConfigurationError(HabitusXError):
    """Settings are missing, malformed, or inconsistent."""


class RegistryError(HabitusXError):
    """The attribution registry could not be loaded or used."""


class RegistryValidationError(RegistryError):
    """The registry file exists but does not satisfy the schema.

    Attributes:
        path: Where the registry was read from, for the error message.
        problems: Human-readable, one-per-line descriptions of what is wrong.
    """

    def __init__(self, path: str, problems: Sequence[str]) -> None:
        """Build a validation error that lists every problem found."""
        self.path = path
        self.problems = tuple(problems)
        bullet_list = "\n".join(f"  - {p}" for p in self.problems)
        super().__init__(f"Registry at {path} is invalid:\n{bullet_list}")


class QueryBudgetExceededError(HabitusXError):
    """A data-warehouse query would bill more bytes than the configured ceiling.

    Raised before the query runs, from a dry run, so no money is spent.
    """

    def __init__(self, estimated_bytes: int, limit_bytes: int, query_name: str) -> None:
        """Record the estimate and the ceiling it exceeded."""
        self.estimated_bytes = estimated_bytes
        self.limit_bytes = limit_bytes
        self.query_name = query_name
        super().__init__(
            f"Query {query_name!r} would bill {estimated_bytes:,} bytes, "
            f"over the ceiling of {limit_bytes:,} bytes. Narrow the date range or raise "
            "HABITUSX_BQ_MAX_BYTES_BILLED deliberately."
        )
