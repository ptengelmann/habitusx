from __future__ import annotations

import json
from datetime import UTC, date, datetime
from pathlib import Path

import pytest
from typer.testing import CliRunner

from habitusx import __version__, cli
from habitusx.adapters.bigquery.gateway import BigQueryGateway
from habitusx.adapters.github.client import GitHubGraphQL
from habitusx.adapters.parquet import write_observations
from habitusx.cli import app
from habitusx.config import get_settings
from habitusx.domain.observations import CommitObservation
from tests.fakes import (
    SHA_A,
    FakeClient,
    FakeTransport,
    fake_job_config,
    gql_commit,
    gql_repo,
    gql_response,
    sample_rows,
)

runner = CliRunner()


def test_version() -> None:
    result = runner.invoke(app, ["version"])
    assert result.exit_code == 0
    assert result.stdout.strip() == __version__


def test_registry_validate_ok(registry_path: Path) -> None:
    result = runner.invoke(app, ["registry", "validate", "--registry", str(registry_path)])
    assert result.exit_code == 0, result.output
    assert "OK:" in result.stdout
    assert "claude-code" in result.stdout


def test_registry_validate_failure_exits_nonzero(tmp_path: Path) -> None:
    bad = tmp_path / "bad.yaml"
    bad.write_text("version: 0\nagents: []\n", encoding="utf-8")
    result = runner.invoke(app, ["registry", "validate", "--registry", str(bad)])
    assert result.exit_code == 1
    assert "is invalid" in result.output


def test_registry_schema_prints_json(schema_path: Path) -> None:
    result = runner.invoke(app, ["registry", "schema"])
    assert result.exit_code == 0
    assert result.stdout == schema_path.read_text(encoding="utf-8")


def test_attribute_from_file(tmp_path: Path, registry_path: Path) -> None:
    message = tmp_path / "msg.txt"
    message.write_text(
        'Revert "Add thing (#12)" (#15)\n\n'
        "This reverts commit 0123456789abcdef0123456789abcdef01234567.\n\n"
        "Co-Authored-By: Claude <noreply@anthropic.com>\n",
        encoding="utf-8",
    )
    result = runner.invoke(
        app,
        ["attribute", "--message-file", str(message), "--registry", str(registry_path)],
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["attribution"]["agent_id"] == "claude-code"
    assert payload["revert"]["original_pr_number"] == 12
    assert payload["revert"]["revert_pr_number"] == 15


def test_attribute_from_stdin_with_no_match(registry_path: Path) -> None:
    result = runner.invoke(
        app, ["attribute", "--registry", str(registry_path)], input="Just a human commit\n"
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload == {"attribution": None, "revert": None}


class TestIngestCommands:
    def test_estimate_without_project_exits_with_hint(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # An empty value overrides any project set in a developer's local .env.
        monkeypatch.setenv("HABITUSX_GCP_PROJECT", "")
        get_settings.cache_clear()
        result = runner.invoke(app, ["ingest", "estimate", "2025-09-01"])
        get_settings.cache_clear()
        assert result.exit_code == 1
        assert "HABITUSX_GCP_PROJECT" in result.output

    def test_bad_day_exits_2(self) -> None:
        result = runner.invoke(app, ["ingest", "estimate", "yesterday"])
        assert result.exit_code == 2
        assert "YYYY-MM-DD" in result.output

    def test_estimate_and_day_with_fake_gateway(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        client = FakeClient(estimate_bytes=16 * 1024**3, rows=sample_rows())
        fake = BigQueryGateway(
            client, max_bytes_billed=25 * 1024**3, job_config_factory=fake_job_config
        )
        monkeypatch.setattr(cli, "_gateway", lambda settings, max_bytes: fake)

        est = runner.invoke(app, ["ingest", "estimate", "2025-09-01"])
        assert est.exit_code == 0, est.output
        assert "16.00 GiB estimated, within" in est.stdout

        day = runner.invoke(app, ["ingest", "day", "2025-09-01", "--out", str(tmp_path)])
        assert day.exit_code == 0, day.output
        assert "3 rows" in day.stdout
        assert "claude-code" in day.stdout
        assert (tmp_path / "observations" / "day=2025-09-01" / "commits.parquet").exists()


class TestPanelCommands:
    def test_build_and_fetch_with_fakes(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        # A one-row census so the treated cohort has a candidate.
        obs = CommitObservation(
            day=date(2025, 9, 1),
            registry_version=1,
            event_id="1",
            repo="a/ai",
            sha=SHA_A,
            pushed_at=datetime(2025, 9, 1, tzinfo=UTC),
            is_distinct=True,
            push_size=1,
            subject="s",
            message="m",
            is_revert=False,
            revert=None,
            author_email_hash=None,
            author_name_hash=None,
            pusher_login_hash=None,
            pusher_is_bot=False,
            attribution=None,
            agent_id="claude-code",
            matched_prefilter=True,
            commits_in_repo_day=1,
        )
        write_observations([obs], tmp_path / "observations" / "day=2025-09-01" / "commits.parquet")

        bq = BigQueryGateway(
            FakeClient(estimate_bytes=1, rows=[{"repo": "c/control"}, {"repo": "a/ai"}]),
            max_bytes_billed=10**9,
            job_config_factory=fake_job_config,
        )
        monkeypatch.setattr(cli, "_gateway", lambda settings, max_bytes: bq)

        build = runner.invoke(
            app,
            [
                "panel",
                "build",
                "--control-day",
                "2026-08-25",
                "--treated-rate",
                "1.0",
                "--control-rate",
                "1.0",
                "--observations",
                str(tmp_path),
                "--out",
                str(tmp_path / "p.json"),
            ],
        )
        assert build.exit_code == 0, build.output
        assert "2 repos" in build.stdout
        assert "treated 1 of 1" in build.stdout
        assert "control 1 of 2" in build.stdout  # a/ai excluded from control because treated

        transport = FakeTransport(
            [
                gql_response(
                    {"r0": gql_repo("a/ai", commits=[gql_commit()]), "r1": gql_repo("c/control")}
                )
            ]
        )
        monkeypatch.setattr(cli, "_github_client", lambda settings: GitHubGraphQL(transport))
        fetch = runner.invoke(
            app,
            [
                "panel",
                "fetch",
                "--since",
                "2026-09-01",
                "--panel",
                str(tmp_path / "p.json"),
                "--out",
                str(tmp_path),
            ],
        )
        assert fetch.exit_code == 0, fetch.output
        assert "2 repos since 2026-09-01" in fetch.stdout
        assert "ok 2" in fetch.stdout
        assert "commits 1" in fetch.stdout
        assert any((tmp_path / "panel").glob("fetched_on=*/commits.parquet"))

    def test_fetch_missing_panel_exits_1(self, tmp_path: Path) -> None:
        result = runner.invoke(
            app, ["panel", "fetch", "--since", "2026-09-01", "--panel", str(tmp_path / "nope.json")]
        )
        assert result.exit_code == 1
        assert "cannot read panel" in result.output
