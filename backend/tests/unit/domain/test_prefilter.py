from __future__ import annotations

import re
from pathlib import Path

import pytest

from habitusx.domain.attribution import (
    Agent,
    AgentStatus,
    AttributionEngine,
    AttributionInput,
    Confidence,
    Registry,
    Signal,
    SignalType,
)
from habitusx.domain.prefilter import (
    NEVER_MATCHES,
    assert_re2_safe,
    compile_prefilter,
    strip_anchors,
)
from habitusx.registry import load_registry


class TestStripAnchors:
    @pytest.mark.parametrize(
        ("pattern", "expected"),
        [
            (r"^noreply@anthropic\.com$", r"noreply@anthropic\.com"),
            (r"^Claude(\s|$)", r"Claude(\s|$)"),
            (r"@aider\.chat$", r"@aider\.chat"),
            (r"plain", "plain"),
            (r"^costs\$", r"^costs\$"[1:]),
        ],
    )
    def test_strips_only_outer_anchors(self, pattern: str, expected: str) -> None:
        assert strip_anchors(pattern) == expected


class TestRe2Safety:
    @pytest.mark.parametrize(
        "bad", [r"(?=x)", r"(?!x)", r"(?<=x)", r"(?<!x)", r"(a)\1", r"(?(1)a|b)"]
    )
    def test_rejects_lookaround_and_backreferences(self, bad: str) -> None:
        with pytest.raises(ValueError, match="RE2"):
            assert_re2_safe(bad)

    @pytest.mark.parametrize(
        "ok", [r"^copilot-swe-agent\[bot\]$", r"(?i)abc", r"(?P<name>x)", r"\d+"]
    )
    def test_accepts_common_syntax(self, ok: str) -> None:
        assert_re2_safe(ok)


class TestCompilePrefilter:
    def test_uses_never_matches_when_a_channel_has_no_signals(
        self, small_registry: Registry
    ) -> None:
        pf = compile_prefilter(small_registry)
        assert pf.author_email == NEVER_MATCHES
        assert re.search(NEVER_MATCHES, "anything at all") is None

    def test_trailer_signals_become_line_anchored_message_patterns(
        self, small_registry: Registry
    ) -> None:
        pf = compile_prefilter(small_registry)
        assert pf.message.startswith("(?im)")
        assert r"^Co\-Authored\-By\s*:[^\n]*bot@alpha\.example" in pf.message
        # Multiline mode: the trailer must match when it is not the first line.
        assert re.search(pf.message, "Subject\n\nCo-Authored-By: Alpha <bot@alpha.example>")
        assert re.search(pf.message, "Subject\n\nBody mentions bot@alpha.example") is None

    def test_author_login_signals_go_to_pusher_login(self, small_registry: Registry) -> None:
        pf = compile_prefilter(small_registry)
        assert re.search(pf.pusher_login, "beta-bot[bot]")
        assert re.search(pf.pusher_login, "octocat") is None

    def test_deprecated_agents_are_excluded(self, small_registry: Registry) -> None:
        pf = compile_prefilter(small_registry)
        assert "gamma" not in pf.pusher_login

    def test_pr_body_signals_are_not_in_any_channel(self, small_registry: Registry) -> None:
        pf = compile_prefilter(small_registry)
        assert (
            "beta.example/tasks"
            not in pf.message + pf.author_email + pf.author_name + pf.pusher_login
        )

    def test_rejects_registry_with_re2_unsafe_pattern(self) -> None:
        registry = Registry(
            version=1,
            agents=(
                Agent(
                    id="x",
                    name="X",
                    vendor="V",
                    status=AgentStatus.VERIFIED,
                    signals=(
                        Signal(
                            id="s",
                            type=SignalType.MESSAGE,
                            pattern=r"(?=lookahead)",
                            confidence=Confidence.HIGH,
                        ),
                    ),
                ),
            ),
        )
        with pytest.raises(ValueError, match="RE2"):
            compile_prefilter(registry)


class TestSupersetProperty:
    """Whatever the engine attributes from a message, the SQL prefilter must also flag.

    If this ever fails, a real commit would be attributed in Python but never reach Python,
    because the SQL would have dropped it.
    """

    @pytest.mark.parametrize(
        "message",
        [
            "Fix\n\nCo-Authored-By: Claude <noreply@anthropic.com>",
            "Fix\n\nCo-Authored-By: Claude Opus 4.1 <noreply@anthropic.com>",
            "Fix\n\nco-authored-by: copilot <175728472+Copilot@users.noreply.github.com>",
            "Fix\n\nCo-authored-by: Cursor <cursoragent@cursor.com>",
            "Fix\n\nCo-authored-by: openhands <openhands@all-hands.dev>",
            "Fix\n\nCo-authored-by: aider (gpt-4o) <noreply@aider.chat>",
            "Fix\n\nClaude-Session: https://claude.ai/code/session_abc",
        ],
    )
    def test_engine_matches_imply_prefilter_matches(
        self, registry_path: Path, message: str
    ) -> None:
        registry = load_registry(registry_path)
        engine = AttributionEngine(registry)
        pf = compile_prefilter(registry)
        assert engine.attribute(AttributionInput(message=message)) is not None
        assert re.search(pf.message, message), "prefilter would drop a commit the engine attributes"

    def test_all_real_registry_patterns_compile_in_python(self, registry_path: Path) -> None:
        pf = compile_prefilter(load_registry(registry_path))
        for pattern in (pf.message, pf.author_email, pf.author_name, pf.pusher_login):
            re.compile(pattern)
