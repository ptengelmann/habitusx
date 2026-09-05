"""Tests against the real registry file and the loader's error reporting."""

from __future__ import annotations

from pathlib import Path

import pytest

from habitusx.domain.attribution import AgentStatus, AttributionInput, Confidence
from habitusx.errors import RegistryError, RegistryValidationError
from habitusx.registry import build_engine, load_registry, registry_json_schema


class TestRealRegistry:
    def test_loads(self, registry_path: Path) -> None:
        registry = load_registry(registry_path)
        assert registry.version >= 1
        assert len(registry.agents) >= 5

    def test_verified_agents_have_evidence_on_high_signals(self, registry_path: Path) -> None:
        registry = load_registry(registry_path)
        missing = [
            f"{agent.id}/{signal.id}"
            for agent in registry.agents
            if agent.status is AgentStatus.VERIFIED
            for signal in agent.signals
            if signal.confidence is Confidence.HIGH and not (signal.evidence or signal.notes)
        ]
        assert missing == [], f"verified agents need evidence/notes on high signals: {missing}"

    def test_committed_schema_matches_models(self, schema_path: Path) -> None:
        expected = registry_json_schema()
        actual = schema_path.read_text(encoding="utf-8")
        assert actual == expected, (
            "registry/schema.json is out of date. Regenerate with:\n"
            "  cd backend && uv run habitusx registry schema > ../registry/schema.json"
        )

    @pytest.mark.parametrize(
        ("message", "author_login", "expected_agent"),
        [
            (
                "Fix bug\n\nCo-Authored-By: Claude <noreply@anthropic.com>",
                None,
                "claude-code",
            ),
            (
                "Fix bug\n\nCo-Authored-By: Claude Opus 4.1 <noreply@anthropic.com>",
                None,
                "claude-code",
            ),
            (
                "Fix bug\n\nCo-authored-by: Copilot <175728472+Copilot@users.noreply.github.com>",
                None,
                "github-copilot",
            ),
            ("Fix bug", "copilot-swe-agent[bot]", "github-copilot"),
            ("Fix bug", "devin-ai-integration[bot]", "devin"),
            ("Fix bug", "google-labs-jules[bot]", "google-jules"),
            (
                "Fix bug\n\nCo-authored-by: Cursor <cursoragent@cursor.com>",
                None,
                "cursor",
            ),
            (
                "Fix bug\n\nCo-authored-by: openhands <openhands@all-hands.dev>",
                None,
                "openhands",
            ),
            (
                "Fix bug\n\nCo-authored-by: aider (gpt-4o) <noreply@aider.chat>",
                None,
                "aider",
            ),
        ],
    )
    def test_known_markers_attribute(
        self, registry_path: Path, message: str, author_login: str | None, expected_agent: str
    ) -> None:
        engine = build_engine(registry_path)
        result = engine.attribute(AttributionInput(message=message, author_login=author_login))
        assert result is not None, f"expected {expected_agent}, got nothing"
        assert result.agent_id == expected_agent

    @pytest.mark.parametrize(
        ("message", "author_login"),
        [
            ("Fix bug\n\nCo-Authored-By: Jane Doe <jane@example.com>", None),
            ("Fix bug\n\nSigned-off-by: Someone <someone@example.com>", "octocat"),
            ("Update README", "dependabot[bot]"),
            ("Claude is a great name for a cat", None),
        ],
    )
    def test_human_and_unrelated_bot_commits_not_attributed(
        self, registry_path: Path, message: str, author_login: str | None
    ) -> None:
        engine = build_engine(registry_path)
        assert (
            engine.attribute(AttributionInput(message=message, author_login=author_login)) is None
        )


class TestLoaderErrors:
    def test_missing_file(self, tmp_path: Path) -> None:
        with pytest.raises(RegistryError, match="cannot read registry"):
            load_registry(tmp_path / "nope.yaml")

    def test_not_yaml(self, tmp_path: Path) -> None:
        path = tmp_path / "bad.yaml"
        path.write_text("version: [unclosed", encoding="utf-8")
        with pytest.raises(RegistryError, match="not valid YAML"):
            load_registry(path)

    def test_top_level_not_mapping(self, tmp_path: Path) -> None:
        path = tmp_path / "list.yaml"
        path.write_text("- just\n- a list\n", encoding="utf-8")
        with pytest.raises(RegistryValidationError) as excinfo:
            load_registry(path)
        assert excinfo.value.problems == ("top level must be a mapping",)

    def test_schema_problems_are_listed_with_locations(self, tmp_path: Path) -> None:
        path = tmp_path / "invalid.yaml"
        path.write_text(
            "version: 1\n"
            "agents:\n"
            "  - id: Bad_ID\n"
            "    name: X\n"
            "    vendor: Y\n"
            "    signals:\n"
            "      - id: s\n"
            "        type: trailer_email\n"
            "        pattern: '('\n"
            "        confidence: high\n",
            encoding="utf-8",
        )
        with pytest.raises(RegistryValidationError) as excinfo:
            load_registry(path)
        text = str(excinfo.value)
        assert "agents.0.id" in text
        assert "agents.0.signals.0" in text
        assert str(path) in text
