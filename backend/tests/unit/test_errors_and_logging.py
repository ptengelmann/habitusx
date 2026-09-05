from __future__ import annotations

import structlog

from habitusx.errors import HabitusXError, QueryBudgetExceededError, RegistryValidationError
from habitusx.logging import configure_logging, get_logger


def test_query_budget_error_message_is_actionable() -> None:
    err = QueryBudgetExceededError(
        estimated_bytes=12_000_000_000, limit_bytes=10_000_000_000, query_name="push_events"
    )
    assert isinstance(err, HabitusXError)
    text = str(err)
    assert "push_events" in text
    assert "12,000,000,000" in text
    assert "HABITUSX_BQ_MAX_BYTES_BILLED" in text


def test_registry_validation_error_lists_problems() -> None:
    err = RegistryValidationError("x.yaml", ["a: bad", "b: worse"])
    assert err.problems == ("a: bad", "b: worse")
    assert "  - a: bad\n  - b: worse" in str(err)


def test_configure_logging_console_and_json() -> None:
    configure_logging("DEBUG", "console")
    log = get_logger("test")
    log.debug("hello", key="value")  # must not raise
    configure_logging("INFO", "json")
    log = get_logger("test")
    log.info("hello", key="value")
    assert structlog.is_configured()
