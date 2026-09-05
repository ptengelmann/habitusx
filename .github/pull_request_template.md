## What

<!-- One or two sentences. What does this change do? -->

## Why

<!-- The problem or decision behind it. Link the ADR if this records an architectural choice. -->

## How to verify

<!-- Commands or steps a reviewer can run. -->

## Checklist

- [ ] Tests cover the change (unit for domain logic, integration where an adapter is touched)
- [ ] `uv run ruff format --check . && uv run ruff check . && uv run mypy && uv run pytest` passes locally
- [ ] Docs updated if behaviour or setup changed (`README`, `docs/`, `registry/README.md`)
- [ ] New architectural decision recorded in `docs/adr/`
- [ ] No secrets, credentials or real users' personal data in the diff
