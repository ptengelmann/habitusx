"""Structured logging.

Console output while developing, JSON lines in production, one call to set up.
Loggers are keyed by module so a log line always says where it came from.
"""

from __future__ import annotations

import logging
import sys
from typing import TYPE_CHECKING

import structlog

if TYPE_CHECKING:
    from habitusx.config import LogFormat


def configure_logging(level: str = "INFO", log_format: LogFormat = "console") -> None:
    """Configure structlog and the stdlib root logger consistently.

    Safe to call more than once; the last call wins.
    """
    shared_processors: list[structlog.types.Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
    ]
    renderer: structlog.types.Processor
    if log_format == "json":
        shared_processors.append(structlog.processors.format_exc_info)
        renderer = structlog.processors.JSONRenderer()
    else:
        renderer = structlog.dev.ConsoleRenderer()

    structlog.configure(
        processors=[*shared_processors, renderer],
        wrapper_class=structlog.make_filtering_bound_logger(logging.getLevelName(level)),
        logger_factory=structlog.PrintLoggerFactory(file=sys.stderr),
        cache_logger_on_first_use=True,
    )
    logging.basicConfig(level=level, stream=sys.stderr, format="%(message)s")


def get_logger(name: str) -> structlog.typing.FilteringBoundLogger:
    """Return a logger with ``logger=name`` bound, normally called with ``__name__``."""
    return structlog.get_logger().bind(logger=name)  # type: ignore[no-any-return]
