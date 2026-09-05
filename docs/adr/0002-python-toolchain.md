# ADR 0002: Python 3.13 with uv, ruff, strict mypy and pytest

Status: accepted. Date: 2026-09-05.

## Context

The backend is a data pipeline plus a small API. Python is the right language for the
BigQuery and data-frame work. The owner's requirement is enterprise-grade robustness:
failures must be loud, typed and local, never "one wrong string and read a million lines".

## Decision

- **Python 3.13**, pinned in `.python-version`. Recent enough for modern typing, old enough
  that every dependency ships wheels.
- **uv** for environments and locking. One tool, a committed `uv.lock`, `--frozen` in CI.
- **ruff** for linting and formatting with a broad rule set (bugbear, security, docstrings,
  annotations, pylint subset). One config, no plugin sprawl.
- **mypy --strict** with the pydantic plugin. If it type-checks, whole classes of bugs are
  gone before tests run.
- **pytest** with **hypothesis** for parsers whose input space is open-ended, and a 90%
  branch-coverage floor enforced in CI.
- **pydantic v2** for every boundary model: frozen, `extra="forbid"`, validated once.
- **structlog** for structured logs, console in dev and JSON in prod.
- **typer** for the CLI, kept thin.

## Consequences

- Contributors need `uv` and nothing else; `uv sync` installs the right Python.
- The linter enforces docstrings on public functions and forbids `print`, commented-out
  code and bare `except`. Noise rules are disabled per-directory for tests, not globally.
- Windows Application Control may block the generated `habitusx.exe` shim; the documented
  invocation is `uv run python -m habitusx.cli`, which works everywhere.
