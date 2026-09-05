"""Load and render the versioned SQL that lives beside this module.

Table names cannot be bound as parameters in BigQuery, so the one templated value, the
day-partition table, is rendered after validating the date. Everything else is a bound
parameter, which keeps user-controlled strings out of the SQL text.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from datetime import date
from importlib import resources
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from habitusx.domain.prefilter import Prefilter

GITHUB_ARCHIVE_DATASET = "githubarchive.day"
_FIRST_DAY = date(2011, 2, 12)  # GitHub Archive's first day.
_TEMPLATE_TOKEN = re.compile(r"\{\{\s*(\w+)\s*\}\}")

PUSH_COMMITS_LAST_DAY = date(2025, 10, 6)
"""Last day whose push events carry commit lists.

On 2025-10-07 GitHub removed commit summaries from Events API push payloads and reduced
pull request payloads to identifiers (github.blog changelog, 2025-08-08). GitHub Archive
mirrors that API, so from that day on it holds no commit messages, authors or trailers.
Commit-level ingest is therefore historical only; see ADR 0006 for the ongoing source.
"""


@dataclass(frozen=True, slots=True)
class RenderedQuery:
    """SQL ready to submit, with its bound parameters and a stable content hash."""

    name: str
    sql: str
    params: dict[str, str] = field(default_factory=dict)

    @property
    def sql_hash(self) -> str:
        """Short hash of the SQL text and parameters, recorded in manifests for reproducibility."""
        digest = hashlib.sha256()
        digest.update(self.sql.encode("utf-8"))
        for key in sorted(self.params):
            digest.update(f"\0{key}={self.params[key]}".encode())
        return digest.hexdigest()[:16]


def table_for_day(day: date) -> str:
    """Return the fully qualified GitHub Archive day table for ``day``.

    Raises:
        ValueError: if ``day`` is before the archive begins or in the future.
    """
    if day < _FIRST_DAY:
        msg = f"GitHub Archive starts on {_FIRST_DAY.isoformat()}; got {day.isoformat()}"
        raise ValueError(msg)
    if day >= date.today():  # archive days are UTC; a same-day table is incomplete
        msg = f"day tables are complete only for past UTC days; got {day.isoformat()}"
        raise ValueError(msg)
    return f"{GITHUB_ARCHIVE_DATASET}.{day.strftime('%Y%m%d')}"


def _load_sql(name: str) -> str:
    return (resources.files(__package__) / "sql" / f"{name}.sql").read_text(encoding="utf-8")


def _render(template: str, values: dict[str, str]) -> str:
    def replace(match: re.Match[str]) -> str:
        key = match.group(1)
        if key not in values:
            msg = f"SQL template references unknown value {{{{ {key} }}}}"
            raise KeyError(msg)
        return values[key]

    return _TEMPLATE_TOKEN.sub(replace, template)


def commits_for_day(day: date, prefilter: Prefilter) -> RenderedQuery:
    """The candidate + revert + baseline extraction for one UTC day.

    Raises:
        ValueError: if ``day`` is outside the archive, or after
            :data:`PUSH_COMMITS_LAST_DAY`, when push events stopped carrying commits.
    """
    if day > PUSH_COMMITS_LAST_DAY:
        msg = (
            f"GitHub Archive push events carry no commit data after "
            f"{PUSH_COMMITS_LAST_DAY.isoformat()} (GitHub Events API change of 2025-10-07); "
            f"got {day.isoformat()}. Commit-level ingest is historical only. "
            "Ongoing data comes from the repository panel (ADR 0006)."
        )
        raise ValueError(msg)
    sql = _render(_load_sql("commits_for_day"), {"table": table_for_day(day)})
    return RenderedQuery(
        name="commits_for_day",
        sql=sql,
        params={
            "message_prefilter": prefilter.message,
            "author_email_prefilter": prefilter.author_email,
            "author_name_prefilter": prefilter.author_name,
            "pusher_login_prefilter": prefilter.pusher_login,
        },
    )


def active_repos_for_day(day: date) -> RenderedQuery:
    """Distinct repositories pushed to on ``day``. Cheap; valid for any archive day."""
    return RenderedQuery(
        name="active_repos_for_day",
        sql=_render(_load_sql("active_repos_for_day"), {"table": table_for_day(day)}),
    )
