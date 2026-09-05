"""Attribution: deciding which AI coding agent, if any, produced a commit or pull request.

The engine is data-driven. Rules live in the registry (``registry/agents.yaml``), each
rule is a *signal* with a type, a regular expression and a confidence level, and the
engine simply evaluates every signal against the input and reports what matched.

Design constraints:

* Deterministic. Same input and registry, same output, always.
* Explainable. Every attribution carries the evidence that produced it.
* Conservative. No match means ``None``; the engine never guesses.
"""

from __future__ import annotations

import re
from enum import StrEnum
from functools import cached_property
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from habitusx.domain.trailers import find_trailers, parse_person

Slug = Annotated[str, StringConstraints(pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$")]


class SignalType(StrEnum):
    """Where in the input a signal looks."""

    TRAILER_NAME = "trailer_name"
    """The name part of a ``Name <email>`` trailer value, e.g. ``Co-Authored-By``."""

    TRAILER_EMAIL = "trailer_email"
    """The email part of a ``Name <email>`` trailer value."""

    TRAILER_PRESENT = "trailer_present"
    """A trailer with the given key exists; the pattern matches its whole value."""

    AUTHOR_LOGIN = "author_login"
    AUTHOR_EMAIL = "author_email"
    AUTHOR_NAME = "author_name"
    MESSAGE = "message"
    PR_BODY = "pr_body"


_TRAILER_TYPES = frozenset(
    {SignalType.TRAILER_NAME, SignalType.TRAILER_EMAIL, SignalType.TRAILER_PRESENT}
)


class Confidence(StrEnum):
    """How strongly a signal implies the agent authored the change."""

    HIGH = "high"
    """The vendor's tooling writes this marker automatically; false positives are rare."""

    MEDIUM = "medium"
    """Usually correct, but users can produce it by hand or the pattern is broad."""

    LOW = "low"
    """Suggestive only. Reported as evidence, never sufficient on its own."""

    @property
    def rank(self) -> int:
        """Numeric order for comparisons; higher is more confident."""
        return {Confidence.LOW: 1, Confidence.MEDIUM: 2, Confidence.HIGH: 3}[self]


class AgentStatus(StrEnum):
    """Whether the community has confirmed an agent's signals against real commits."""

    VERIFIED = "verified"
    NEEDS_VERIFICATION = "needs_verification"
    DEPRECATED = "deprecated"


class Signal(BaseModel):
    """One detection rule."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: Slug
    type: SignalType
    pattern: str = Field(description="Python regular expression, searched (not anchored).")
    trailer_key: str | None = Field(
        default=None,
        description="Required for trailer signal types, e.g. 'Co-Authored-By'.",
    )
    confidence: Confidence
    case_sensitive: bool = False
    evidence: str | None = Field(
        default=None,
        description="URL or note showing this marker in the wild.",
    )
    notes: str | None = None

    @model_validator(mode="after")
    def _check_shape(self) -> Signal:
        if self.type in _TRAILER_TYPES and not self.trailer_key:
            msg = f"signal {self.id!r}: trailer_key is required for type {self.type.value!r}"
            raise ValueError(msg)
        if self.type not in _TRAILER_TYPES and self.trailer_key:
            msg = f"signal {self.id!r}: trailer_key is only valid for trailer signal types"
            raise ValueError(msg)
        try:
            re.compile(self.pattern)
        except re.error as exc:
            msg = f"signal {self.id!r}: invalid regular expression: {exc}"
            raise ValueError(msg) from exc
        return self

    @cached_property
    def regex(self) -> re.Pattern[str]:
        """The compiled pattern, honouring ``case_sensitive``."""
        flags = 0 if self.case_sensitive else re.IGNORECASE
        return re.compile(self.pattern, flags)


class Agent(BaseModel):
    """An AI coding agent and the signals that identify its work."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: Slug
    name: str
    vendor: str
    homepage: str | None = None
    status: AgentStatus = AgentStatus.NEEDS_VERIFICATION
    signals: tuple[Signal, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def _unique_signal_ids(self) -> Agent:
        seen: set[str] = set()
        for signal in self.signals:
            if signal.id in seen:
                msg = f"agent {self.id!r}: duplicate signal id {signal.id!r}"
                raise ValueError(msg)
            seen.add(signal.id)
        return self


class Registry(BaseModel):
    """The full set of agents. This is the schema of ``registry/agents.yaml``."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    version: int = Field(ge=1)
    agents: tuple[Agent, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def _unique_agent_ids(self) -> Registry:
        seen: set[str] = set()
        for agent in self.agents:
            if agent.id in seen:
                msg = f"duplicate agent id {agent.id!r}"
                raise ValueError(msg)
            seen.add(agent.id)
        return self

    def agent(self, agent_id: str) -> Agent:
        """Look up an agent by id.

        Raises:
            KeyError: if no agent has that id.
        """
        for candidate in self.agents:
            if candidate.id == agent_id:
                return candidate
        raise KeyError(agent_id)


class AttributionInput(BaseModel):
    """Everything the engine may look at for one commit or pull request."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    message: str = ""
    author_login: str | None = None
    author_email: str | None = None
    author_name: str | None = None
    pr_body: str | None = None


class Evidence(BaseModel):
    """One signal that matched, with the text it matched on."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    agent_id: str
    signal_id: str
    signal_type: SignalType
    confidence: Confidence
    matched: str


class Attribution(BaseModel):
    """The engine's verdict for one input."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    agent_id: str = Field(description="The best-supported agent.")
    confidence: Confidence = Field(description="Confidence of the strongest signal.")
    evidence: tuple[Evidence, ...] = Field(
        min_length=1,
        description="All matching signals across all agents, strongest first.",
    )

    @property
    def agent_ids(self) -> tuple[str, ...]:
        """Every agent with at least one matching signal, in evidence order."""
        seen: dict[str, None] = {}
        for item in self.evidence:
            seen.setdefault(item.agent_id, None)
        return tuple(seen)


class AttributionEngine:
    """Evaluate registry signals against inputs."""

    def __init__(self, registry: Registry) -> None:
        """Bind the engine to a validated registry."""
        self._registry = registry
        self._agent_order = {agent.id: index for index, agent in enumerate(registry.agents)}

    @property
    def registry(self) -> Registry:
        """The registry this engine evaluates."""
        return self._registry

    def evaluate(self, item: AttributionInput) -> tuple[Evidence, ...]:
        """Return every matching signal, strongest first, then in registry order."""
        found: list[Evidence] = []
        for agent in self._registry.agents:
            if agent.status is AgentStatus.DEPRECATED:
                continue
            for signal in agent.signals:
                matched = _match(signal, item)
                if matched is not None:
                    found.append(
                        Evidence(
                            agent_id=agent.id,
                            signal_id=signal.id,
                            signal_type=signal.type,
                            confidence=signal.confidence,
                            matched=matched,
                        )
                    )
        found.sort(key=lambda e: (-e.confidence.rank, self._agent_order[e.agent_id]))
        return tuple(found)

    def attribute(self, item: AttributionInput) -> Attribution | None:
        """Return the best-supported attribution, or ``None`` if nothing matched.

        ``LOW`` confidence evidence alone is not enough to attribute; it is only reported
        alongside a medium or high signal.
        """
        evidence = self.evaluate(item)
        if not evidence:
            return None
        best = evidence[0]
        if best.confidence is Confidence.LOW:
            return None
        return Attribution(agent_id=best.agent_id, confidence=best.confidence, evidence=evidence)


def _match(signal: Signal, item: AttributionInput) -> str | None:
    """Return the matched text if ``signal`` fires on ``item``."""
    if signal.type in _TRAILER_TYPES:
        assert signal.trailer_key is not None  # noqa: S101 - enforced by the model validator
        for value in find_trailers(item.message, signal.trailer_key):
            candidate = _trailer_field(signal.type, value)
            if candidate is not None and signal.regex.search(candidate):
                return candidate
        return None

    field = {
        SignalType.AUTHOR_LOGIN: item.author_login,
        SignalType.AUTHOR_EMAIL: item.author_email,
        SignalType.AUTHOR_NAME: item.author_name,
        SignalType.MESSAGE: item.message,
        SignalType.PR_BODY: item.pr_body,
    }[signal.type]
    if not field:
        return None
    found = signal.regex.search(field)
    return found.group(0) if found else None


def _trailer_field(kind: SignalType, value: str) -> str | None:
    if kind is SignalType.TRAILER_PRESENT:
        return value
    person = parse_person(value)
    if person is None:
        # A bare value with no <email>; treat the whole thing as the name.
        return value if kind is SignalType.TRAILER_NAME else None
    return person.name if kind is SignalType.TRAILER_NAME else person.email
