from __future__ import annotations

import pytest
from pydantic import ValidationError

from habitusx.domain.attribution import (
    Agent,
    AttributionEngine,
    AttributionInput,
    Confidence,
    Registry,
    Signal,
    SignalType,
)


def msg(*trailers: str, body: str = "Body.") -> str:
    return "Subject\n\n" + body + "\n\n" + "\n".join(trailers) + "\n"


class TestEngineWithSyntheticRegistry:
    def test_no_signals_means_none(self, engine: AttributionEngine) -> None:
        assert engine.attribute(AttributionInput(message="Plain human commit")) is None
        assert engine.evaluate(AttributionInput(message="Plain human commit")) == ()

    def test_trailer_email_high_confidence(self, engine: AttributionEngine) -> None:
        item = AttributionInput(message=msg("Co-Authored-By: Alpha <bot@alpha.example>"))
        result = engine.attribute(item)
        assert result is not None
        assert result.agent_id == "alpha-agent"
        assert result.confidence is Confidence.HIGH
        # Both the email and the name signal fire; email is stronger and comes first.
        assert [e.signal_id for e in result.evidence] == ["alpha-email", "alpha-name"]
        assert result.evidence[0].matched == "bot@alpha.example"

    def test_trailer_name_alone_is_medium(self, engine: AttributionEngine) -> None:
        item = AttributionInput(message=msg("Co-Authored-By: Alpha Model 3 <someone@else.example>"))
        result = engine.attribute(item)
        assert result is not None
        assert result.confidence is Confidence.MEDIUM
        assert result.evidence[0].matched == "Alpha Model 3"

    def test_trailer_key_is_case_insensitive(self, engine: AttributionEngine) -> None:
        item = AttributionInput(message=msg("co-authored-by: Alpha <bot@alpha.example>"))
        assert engine.attribute(item) is not None

    def test_trailer_in_prose_does_not_count(self, engine: AttributionEngine) -> None:
        # The marker is in the body, not in a trailer block, so it must be ignored.
        item = AttributionInput(
            message="Subject\n\nCo-Authored-By: Alpha <bot@alpha.example> was mentioned here.\n"
            "And more prose follows."
        )
        assert engine.attribute(item) is None

    def test_low_confidence_alone_does_not_attribute(self, engine: AttributionEngine) -> None:
        item = AttributionInput(message="Subject\n\nThis was generated with alpha.")
        assert engine.attribute(item) is None
        evidence = engine.evaluate(item)
        assert len(evidence) == 1
        assert evidence[0].confidence is Confidence.LOW

    def test_low_confidence_is_reported_alongside_stronger_signal(
        self, engine: AttributionEngine
    ) -> None:
        item = AttributionInput(
            message=msg("Co-Authored-By: Alpha <bot@alpha.example>", body="generated with alpha")
        )
        result = engine.attribute(item)
        assert result is not None
        assert [e.confidence for e in result.evidence] == [
            Confidence.HIGH,
            Confidence.MEDIUM,
            Confidence.LOW,
        ]

    def test_author_login_signal(self, engine: AttributionEngine) -> None:
        item = AttributionInput(message="Subject", author_login="beta-bot[bot]")
        result = engine.attribute(item)
        assert result is not None
        assert result.agent_id == "beta-bot"
        assert result.evidence[0].signal_type is SignalType.AUTHOR_LOGIN

    def test_pr_body_signal(self, engine: AttributionEngine) -> None:
        item = AttributionInput(
            message="Subject", pr_body="Done.\n\nTask: https://beta.example/tasks/abc123"
        )
        result = engine.attribute(item)
        assert result is not None
        assert result.agent_id == "beta-bot"
        assert result.confidence is Confidence.MEDIUM

    def test_multiple_agents_all_reported_best_wins(self, engine: AttributionEngine) -> None:
        item = AttributionInput(
            message=msg("Co-Authored-By: Alpha Thing <x@y.example>"),  # medium
            author_login="beta-bot[bot]",  # high
        )
        result = engine.attribute(item)
        assert result is not None
        assert result.agent_id == "beta-bot"
        assert result.agent_ids == ("beta-bot", "alpha-agent")

    def test_tie_on_confidence_breaks_by_registry_order(self, engine: AttributionEngine) -> None:
        item = AttributionInput(
            message=msg("Co-Authored-By: Alpha <bot@alpha.example>"),  # high, agent index 0
            author_login="beta-bot[bot]",  # high, agent index 1
        )
        result = engine.attribute(item)
        assert result is not None
        assert result.agent_id == "alpha-agent"

    def test_deprecated_agents_never_match(self, engine: AttributionEngine) -> None:
        assert engine.attribute(AttributionInput(message="x", author_login="gamma")) is None

    def test_missing_fields_do_not_match(self, engine: AttributionEngine) -> None:
        assert engine.evaluate(AttributionInput()) == ()

    def test_deterministic(self, engine: AttributionEngine) -> None:
        item = AttributionInput(
            message=msg("Co-Authored-By: Alpha <bot@alpha.example>"), author_login="beta-bot[bot]"
        )
        assert engine.attribute(item) == engine.attribute(item)


class TestSignalValidation:
    def test_trailer_type_requires_trailer_key(self) -> None:
        with pytest.raises(ValidationError, match="trailer_key is required"):
            Signal(id="x", type=SignalType.TRAILER_EMAIL, pattern="a", confidence=Confidence.HIGH)

    def test_non_trailer_type_rejects_trailer_key(self) -> None:
        with pytest.raises(ValidationError, match="only valid for trailer"):
            Signal(
                id="x",
                type=SignalType.AUTHOR_LOGIN,
                trailer_key="Co-Authored-By",
                pattern="a",
                confidence=Confidence.HIGH,
            )

    def test_invalid_regex_rejected(self) -> None:
        with pytest.raises(ValidationError, match="invalid regular expression"):
            Signal(id="x", type=SignalType.MESSAGE, pattern="(unclosed", confidence=Confidence.LOW)

    def test_case_sensitive_flag(self) -> None:
        sensitive = Signal(
            id="x",
            type=SignalType.MESSAGE,
            pattern="Bot",
            confidence=Confidence.LOW,
            case_sensitive=True,
        )
        insensitive = Signal(
            id="y", type=SignalType.MESSAGE, pattern="Bot", confidence=Confidence.LOW
        )
        assert sensitive.regex.search("bot") is None
        assert insensitive.regex.search("bot") is not None

    @pytest.mark.parametrize("bad_id", ["Bad", "has space", "under_score", "-lead", "trail-", ""])
    def test_slug_ids_enforced(self, bad_id: str) -> None:
        with pytest.raises(ValidationError):
            Signal(id=bad_id, type=SignalType.MESSAGE, pattern="a", confidence=Confidence.LOW)


class TestRegistryValidation:
    def _signal(self, sid: str = "s") -> Signal:
        return Signal(id=sid, type=SignalType.MESSAGE, pattern="a", confidence=Confidence.HIGH)

    def test_duplicate_agent_ids_rejected(self) -> None:
        agent = Agent(id="dup", name="D", vendor="V", signals=(self._signal(),))
        with pytest.raises(ValidationError, match="duplicate agent id"):
            Registry(version=1, agents=(agent, agent))

    def test_duplicate_signal_ids_within_agent_rejected(self) -> None:
        with pytest.raises(ValidationError, match="duplicate signal id"):
            Agent(id="a", name="A", vendor="V", signals=(self._signal("s"), self._signal("s")))

    def test_agent_requires_at_least_one_signal(self) -> None:
        with pytest.raises(ValidationError):
            Agent(id="a", name="A", vendor="V", signals=())

    def test_lookup(self, small_registry: Registry) -> None:
        assert small_registry.agent("beta-bot").name == "Beta"
        with pytest.raises(KeyError):
            small_registry.agent("nope")

    def test_confidence_rank_order(self) -> None:
        assert Confidence.LOW.rank < Confidence.MEDIUM.rank < Confidence.HIGH.rank
