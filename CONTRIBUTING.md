# Contributing to HabitusX

Thank you for helping build a neutral record of how AI-written code holds up. There are
two kinds of contribution and they have different bars.

## Registry contributions (most welcome)

Adding or correcting how an AI coding agent is detected. No Python required.

1. Edit `registry/agents.yaml`. Read `registry/README.md` first for the signal model and
   the verification standard.
2. From `backend/`, run `uv run python -m habitusx.cli registry validate`.
3. Add a redacted example to `backend/tests/unit/registry/test_loader.py` so the marker is
   pinned by a test.
4. Open a pull request. Link public evidence for every `high` confidence signal.

Never include a real person's name or email in examples. Bot accounts and vendor
no-reply addresses are fine. Registry data is CC BY 4.0; by contributing you agree to that.

## Code contributions

1. Open an issue first for anything beyond a small fix, so the approach is agreed before
   the work is done. Architectural changes need an ADR in `docs/adr/`.
2. Branch from `main`. Branch names: `feat/...`, `fix/...`, `docs/...`, `chore/...`.
3. Keep the domain package pure: no I/O in `backend/src/habitusx/domain`.
4. Run the full gate before pushing:

   ```powershell
   cd backend
   uv run ruff format . ; uv run ruff check . ; uv run mypy ; uv run pytest --cov
   ```

5. Open a pull request with a Conventional Commits title (`feat:`, `fix:`, `docs:`,
   `refactor:`, `test:`, `chore:`, `ci:`, `perf:`). Fill in the template. CI must be green.

Pull requests are squash-merged with the title as the commit subject, so make the title
say what changed.

## What we will not merge

- Detection heuristics without published precision (guessing that code is AI-written
  from style).
- Anything that scores or ranks agents based on vendor payment or preference.
- Code that reads personal data beyond what GitHub already publishes in public events.

## Licence

Code is under the Business Source License 1.1 (see `LICENSE`), converting to Apache 2.0
on the change date. Registry data is CC BY 4.0 (see `registry/LICENSE`). By contributing
you agree your contribution is licensed accordingly.
