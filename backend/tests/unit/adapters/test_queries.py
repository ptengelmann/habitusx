from __future__ import annotations

from datetime import date, timedelta

import pytest

from habitusx.adapters.bigquery.queries import (
    GITHUB_ARCHIVE_DATASET,
    PUSH_COMMITS_LAST_DAY,
    RenderedQuery,
    _render,
    commits_for_day,
    table_for_day,
)
from habitusx.domain.prefilter import Prefilter

PF = Prefilter(message="(?im)m", author_email="(?i)e", author_name="(?i)n", pusher_login="(?i)l")


class TestTableForDay:
    def test_formats_day_table(self) -> None:
        assert table_for_day(date(2025, 9, 1)) == f"{GITHUB_ARCHIVE_DATASET}.20250901"

    def test_rejects_days_before_the_archive(self) -> None:
        with pytest.raises(ValueError, match="starts on"):
            table_for_day(date(2011, 1, 1))

    @pytest.mark.parametrize("offset", [0, 1, 30])
    def test_rejects_today_and_future(self, offset: int) -> None:
        with pytest.raises(ValueError, match="past UTC days"):
            table_for_day(date.today() + timedelta(days=offset))


class TestRender:
    def test_replaces_known_tokens(self) -> None:
        assert _render("FROM `{{ table }}` x {{table}}", {"table": "t"}) == "FROM `t` x t"

    def test_unknown_token_raises(self) -> None:
        with pytest.raises(KeyError, match="unknown value"):
            _render("{{ nope }}", {"table": "t"})


class TestCommitsForDay:
    def test_renders_table_and_binds_prefilter(self) -> None:
        q = commits_for_day(date(2025, 9, 1), PF)
        assert q.name == "commits_for_day"
        assert "`githubarchive.day.20250901`" in q.sql
        assert "{{" not in q.sql
        assert q.params == {
            "message_prefilter": "(?im)m",
            "author_email_prefilter": "(?i)e",
            "author_name_prefilter": "(?i)n",
            "pusher_login_prefilter": "(?i)l",
        }
        for name in q.params:
            assert f"@{name}" in q.sql, f"SQL never uses parameter {name}"

    def test_sql_hash_is_stable_and_sensitive(self) -> None:
        a = commits_for_day(date(2025, 9, 1), PF)
        b = commits_for_day(date(2025, 9, 1), PF)
        c = commits_for_day(date(2025, 9, 2), PF)
        d = commits_for_day(date(2025, 9, 1), Prefilter("x", "e", "n", "l"))
        assert a.sql_hash == b.sql_hash
        assert a.sql_hash != c.sql_hash
        assert a.sql_hash != d.sql_hash

    def test_selects_only_needed_columns(self) -> None:
        sql = commits_for_day(date(2025, 9, 1), PF).sql
        assert "SELECT *" not in sql.split("flagged AS")[0], "outer selects must be explicit"
        assert "type = 'PushEvent'" in sql

    def test_rendered_query_is_frozen(self) -> None:
        q = RenderedQuery(name="n", sql="s")
        with pytest.raises(AttributeError):
            q.sql = "changed"  # type: ignore[misc]


class TestCommitDataCutoff:
    def test_last_day_with_commits_is_allowed(self) -> None:
        q = commits_for_day(PUSH_COMMITS_LAST_DAY, PF)
        assert "20251006" in q.sql

    def test_day_after_cutoff_is_refused_with_explanation(self) -> None:
        with pytest.raises(ValueError, match="no commit data after 2025-10-06") as excinfo:
            commits_for_day(date(2025, 10, 7), PF)
        assert "ADR 0006" in str(excinfo.value)
