"""Shared fixtures."""

from __future__ import annotations

from pathlib import Path

import pytest

from habitusx.domain.attribution import (
    Agent,
    AgentStatus,
    AttributionEngine,
    Confidence,
    Registry,
    Signal,
    SignalType,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
REGISTRY_PATH = REPO_ROOT / "registry" / "agents.yaml"
SCHEMA_PATH = REPO_ROOT / "registry" / "schema.json"


@pytest.fixture(scope="session")
def repo_root() -> Path:
    return REPO_ROOT


@pytest.fixture(scope="session")
def registry_path() -> Path:
    return REGISTRY_PATH


@pytest.fixture(scope="session")
def schema_path() -> Path:
    return SCHEMA_PATH


@pytest.fixture
def small_registry() -> Registry:
    """A minimal, fully synthetic registry for engine tests.

    Independent of the real registry so changes to the data file cannot break engine tests.
    """
    return Registry(
        version=1,
        agents=(
            Agent(
                id="alpha-agent",
                name="Alpha",
                vendor="Alpha Corp",
                status=AgentStatus.VERIFIED,
                signals=(
                    Signal(
                        id="alpha-email",
                        type=SignalType.TRAILER_EMAIL,
                        trailer_key="Co-Authored-By",
                        pattern=r"^bot@alpha\.example$",
                        confidence=Confidence.HIGH,
                    ),
                    Signal(
                        id="alpha-name",
                        type=SignalType.TRAILER_NAME,
                        trailer_key="Co-Authored-By",
                        pattern=r"^Alpha(\s|$)",
                        confidence=Confidence.MEDIUM,
                    ),
                    Signal(
                        id="alpha-hint",
                        type=SignalType.MESSAGE,
                        pattern=r"generated with alpha",
                        confidence=Confidence.LOW,
                    ),
                ),
            ),
            Agent(
                id="beta-bot",
                name="Beta",
                vendor="Beta Inc",
                status=AgentStatus.NEEDS_VERIFICATION,
                signals=(
                    Signal(
                        id="beta-login",
                        type=SignalType.AUTHOR_LOGIN,
                        pattern=r"^beta-bot\[bot\]$",
                        confidence=Confidence.HIGH,
                    ),
                    Signal(
                        id="beta-pr-link",
                        type=SignalType.PR_BODY,
                        pattern=r"beta\.example/tasks/",
                        confidence=Confidence.MEDIUM,
                    ),
                ),
            ),
            Agent(
                id="gamma-old",
                name="Gamma",
                vendor="Gamma",
                status=AgentStatus.DEPRECATED,
                signals=(
                    Signal(
                        id="gamma-login",
                        type=SignalType.AUTHOR_LOGIN,
                        pattern=r"^gamma$",
                        confidence=Confidence.HIGH,
                    ),
                ),
            ),
        ),
    )


@pytest.fixture
def engine(small_registry: Registry) -> AttributionEngine:
    return AttributionEngine(small_registry)
