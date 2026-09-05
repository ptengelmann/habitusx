# Architecture

HabitusX turns public GitHub activity into a continuous, neutral index of what happens to
AI-written code after it lands. This document describes the shape of the system, what
exists today, and what each later stage adds. Decisions with trade-offs are recorded as
ADRs in `docs/adr/`.

## Principles

1. **Pure core.** Everything that decides something (is this commit AI-authored, is this a
   revert, what counts as a clean outcome) lives in `backend/src/habitusx/domain` with no
   I/O, is deterministic, and is unit-tested exhaustively. Adapters and pipelines stay thin.
2. **Explainable results.** Every attribution carries the evidence that produced it. Every
   aggregate can be traced to the rows and the registry version that produced it.
3. **Data-driven detection.** Which agents exist and how to detect them is data
   (`registry/agents.yaml`), validated by schema and tests, contributable by pull request.
4. **Append-only history.** Raw observations are never edited. Re-running with a new
   registry or method adds rows tagged with the new version; it never overwrites.
5. **Cost is a correctness property.** Every warehouse query dry-runs first and carries a
   hard bytes-billed ceiling. A query that would blow the budget fails before it runs.

## Layers

```
                 ┌────────────────────────────────────────────┐
                 │ frontend/  (Next.js, later)                 │
                 │ public index, per-agent pages, badges       │
                 └───────────────────────┬────────────────────┘
                                         │ HTTPS/JSON
┌────────────────────────────────────────┼────────────────────────────────────────┐
│ backend/src/habitusx                   ▼                                        │
│                                                                                 │
│  api/          FastAPI: read-only endpoints, badge SVGs            (PR 4)       │
│  services/     pipelines: ingest -> attribute -> outcomes -> aggregate (PR 2-3) │
│  adapters/     bigquery (GitHub Archive), postgres (serving), github (PR 2-3)   │
│  domain/       trailers, commits, reverts, attribution engine      (PR 1, done) │
│  registry/     loads registry/agents.yaml into domain models       (PR 1, done) │
│  config/errors/logging                                              (PR 1, done) │
└─────────────────────────────────────────────────────────────────────────────────┘
                     ▲                                        │
                     │ reads                                  │ writes
        ┌────────────┴────────────┐              ┌────────────▼────────────┐
        │ BigQuery                │              │ Postgres                │
        │ githubarchive.day.*     │              │ attributed commits,     │
        │ (public, partitioned)   │              │ outcomes, daily         │
        └─────────────────────────┘              │ aggregates, registry    │
                                                 │ versions                │
                                                 └─────────────────────────┘
```

## Data flow

1. **Ingest.** A daily job queries one day-partition of GitHub Archive for push events and
   pull request events. Only fields the pipeline needs are selected; the query is dry-run
   and rejected if it would exceed the byte ceiling.
2. **Attribute.** Each commit and PR is passed through the attribution engine with the
   current registry version. Matches are stored with their evidence. Non-matches are
   counted for the baseline but not stored individually.
3. **Outcomes.** Revert commits are parsed and joined back to the commits they undo. PR
   events supply merged/closed state, time to merge and review comment counts. Later
   stages add follow-up-fix detection and code survival on samples.
4. **Aggregate.** Nightly rollups by agent, language, repository size class and week.
   Human-authored commits in the same repositories form the baseline, so comparisons are
   within-repo rather than across the whole of GitHub.
5. **Serve.** The API reads aggregates only. Badges are rendered from the same tables.

## What exists now (PR 1)

- Domain: git trailer parser following `git interpret-trailers` semantics, commit model
  with validated SHA and repo name, revert/reapply parser, data-driven attribution engine
  with confidence ranking and full evidence.
- Registry: ten agents with signals marked `verified` or `needs_verification`, schema
  generated from the models and checked in, loader with human-readable validation errors.
- Tooling: uv, ruff, strict mypy, pytest with hypothesis, 90% coverage floor, CI.

## Known limitations

- Attribution only sees agents that leave markers. Users can disable markers. The index
  reports attribution coverage and compares within-repo to limit the bias.
- Revert rate is a proxy for "did not survive", not for quality. The methodology page
  says so plainly.
- GitHub Archive push events carry at most twenty commits per push and no file lists.
  Follow-up-fix detection therefore needs the GitHub API on a sample, not the archive.
