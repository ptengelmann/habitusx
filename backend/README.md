# HabitusX backend

Python 3.13, managed with [uv](https://docs.astral.sh/uv/). Strict typing, one linter,
tests that run in seconds. Everything below runs from this directory.

## Setup

```powershell
uv sync                      # creates .venv, installs Python 3.13 if needed, locks deps
uv run habitusx --help
```

## Quality gate

These four commands are what CI runs. If they pass locally, CI passes.

```powershell
uv run ruff format --check .
uv run ruff check .
uv run mypy
uv run pytest --cov
```

`uv run ruff format .` fixes formatting; `uv run ruff check --fix .` fixes what it safely can.

## Layout

```
src/habitusx/
  domain/        pure logic, no I/O: trailers, commits, reverts, attribution engine
  registry/      loads and validates registry/agents.yaml into domain models
  config.py      environment-driven settings (HABITUSX_* variables)
  errors.py      typed exception hierarchy
  logging.py     structlog setup
  cli.py         typer CLI, thin
tests/
  unit/          mirrors src; property tests with hypothesis where inputs are open-ended
```

Adapters (BigQuery, Postgres, GitHub), pipelines and the HTTP API arrive in later PRs
and slot in beside `domain/` without changing it.

## Conventions

- Pydantic models are frozen and reject unknown fields.
- Public functions have docstrings; the linter enforces it.
- No bare `except`, no `print` outside the CLI, no commented-out code.
- Every error a user can hit derives from `HabitusXError` and says what to do next.
