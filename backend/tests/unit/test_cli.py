from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from habitusx import __version__, cli
from habitusx.adapters.bigquery.gateway import BigQueryGateway
from habitusx.cli import app
from habitusx.config import get_settings
from tests.fakes import FakeClient, fake_job_config, sample_rows

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
