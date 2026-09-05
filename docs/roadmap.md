# Roadmap

Delivered as a sequence of pull requests, each independently reviewable and green in CI.
The order is chosen so that every stage produces something usable.

| PR | Scope | Output |
|---|---|---|
| 1 | Foundation: repo, CI, domain core, attribution registry, CLI | Deterministic, tested attribution and revert detection. This PR. |
| 2 | BigQuery adapter and ingest pipeline | Versioned SQL, dry-run budget guard, one day of GitHub Archive -> attributed commits and PRs as Parquet/JSONL. First real numbers in a notebook. |
| 3 | Postgres serving store and aggregates | SQLAlchemy models, Alembic migrations, nightly rollups by agent/language/week with within-repo baselines. Backfill of the last 90 days. |
| 4 | Public API and badges | FastAPI read-only endpoints, per-repo and per-agent badge SVGs, OpenAPI spec, rate limiting. |
| 5 | Frontend | Next.js index, per-agent pages, methodology page, badge embed snippets. Design reference supplied by the owner. |
| 6 | Launch content | First monthly report, methodology published, registry open for contributions. |
| 7 | GitHub App (private repos) | Installable app computing the same metrics for an organisation against the public baseline. First paid layer. |

## Non-goals for now

- Judging code quality directly. Outcomes are what we measure.
- Detecting AI code without markers. Out of scope until an approach with published
  precision exists.
- Any vendor-paid placement or scoring.
