from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from habitusx import __version__
from habitusx.cli import app

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
