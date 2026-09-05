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

## Ingest a day of GitHub Archive

Needs `HABITUSX_GCP_PROJECT` in `backend/.env` and a completed
`gcloud auth application-default login`. Dry runs are free; a full day scans ~15 GiB
against a 1 TiB monthly free tier.

```powershell
uv run python -m habitusx.cli ingest estimate 2025-09-01   # bytes it would scan, spends nothing
uv run python -m habitusx.cli ingest day 2025-09-01        # -> data/observations/day=2025-09-01/
```

Commit-level ingest works for days up to 2025-10-06 only. GitHub removed commit data from
public events on 2025-10-07; see `docs/adr/0006-...md` for what replaces it.

Live tests (dry runs, free): `HABITUSX_RUN_INTEGRATION=1 uv run pytest -m integration`.

## Layout

```
src/habitusx/
  domain/        pure logic, no I/O: trailers, commits, reverts, attribution engine,
                 registry -> SQL prefilter compiler, observation model
  adapters/      bigquery/ (gateway with budget guard, versioned SQL), parquet.py
  services/      ingest.py: one day in, Parquet + manifest out
  registry/      loads and validates registry/agents.yaml into domain models
  config.py      environment-driven settings (HABITUSX_* variables)
  errors.py      typed exception hierarchy
  logging.py     structlog setup
  cli.py         typer CLI, thin
tests/
  unit/          mirrors src; property tests with hypothesis where inputs are open-ended
```

The GitHub API adapter and repository panel (PR 3), Postgres (PR 4) and the HTTP API
(PR 5) slot in beside these without changing `domain/`.

## Conventions

- Pydantic models are frozen and reject unknown fields.
- Public functions have docstrings; the linter enforces it.
- No bare `except`, no `print` outside the CLI, no commented-out code.
- Every error a user can hit derives from `HabitusXError` and says what to do next.
