# HabitusX

**The AI Code Outcomes Index.** What happens to AI-written code after it lands.

Millions of public GitHub commits now carry markers from AI coding agents. Existing
trackers count them. HabitusX measures what happens next: revert rate, pull request
acceptance, review burden and survival, by agent, language and repository, against a
human baseline from the same repositories. Continuous, neutral, methodology published.

## Repository layout

```
backend/     Python pipeline, attribution engine, API      see backend/README.md
frontend/    Next.js site (not started; UI phase)
registry/    community-contributable agent detection rules  see registry/README.md
docs/        architecture, methodology, roadmap, ADRs
```

## Status

PR 1 (foundation) delivers the deterministic core: git trailer parsing, revert detection,
a data-driven attribution engine, a validated registry of ten agents, and the full quality
gate in CI. Data ingestion from GitHub Archive is PR 2. See `docs/roadmap.md`.

## Develop

```powershell
cd backend
uv sync
uv run python -m habitusx.cli --help
uv run python -m habitusx.cli registry validate
uv run ruff format --check . ; uv run ruff check . ; uv run mypy ; uv run pytest --cov
```

Try the engine on a message:

```powershell
"Fix retry`n`nCo-Authored-By: Claude <noreply@anthropic.com>" | uv run python -m habitusx.cli attribute
```

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). Every change goes through a pull request with CI green. Commit messages follow
Conventional Commits (`feat:`, `fix:`, `docs:`, ...). Architectural decisions get an ADR in
`docs/adr/`. Registry contributions: `registry/README.md`.

## License

Code: [Business Source License 1.1](LICENSE), converting to Apache 2.0 on 2029-09-05. You may run it, modify it, and analyse your own repositories with it; you may not offer it as a competing hosted service before the change date.
Registry data: [CC BY 4.0](registry/LICENSE).

## Principles

Pure, tested core. Explainable results. Detection rules as data. Append-only history.
Cost ceilings enforced before a query runs. No vendor-paid placement, ever.
