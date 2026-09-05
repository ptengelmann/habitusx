# Roadmap

Delivered as a sequence of pull requests, each independently reviewable and green in CI.
The order is chosen so that every stage produces something usable.

| PR | Scope | Output |
|---|---|---|
| 1 | Foundation: repo, CI, domain core, attribution registry, CLI | Deterministic, tested attribution and revert detection. This PR. |
| 2 | BigQuery adapter and historical ingest | Versioned SQL, dry-run budget guard, one day of GitHub Archive -> attributed commits as Parquet with manifest. Discovered and documented the October 2025 Events API change (ADR 0006). |
| 3 | GitHub API adapter and repository panel | Deterministic panel (treated cohort + hash-sampled control), GraphQL-batched enrichment of commits and pull requests since a watermark, same Parquet + manifest output. Panel v1 built (3,763 repos) and fetched live. ADR 0007. Done. |
| 3b | Historical backfill | Source A for 2025-02-01 to 2025-10-06 under a monthly BigQuery budget. |
| 4 | Postgres serving store and aggregates | SQLAlchemy models, Alembic migrations, nightly rollups by agent/language/week with within-repo baselines, source and panel version on every row. |
| 5 | Public API and badges | FastAPI read-only endpoints, per-repo and per-agent badge SVGs, OpenAPI spec, rate limiting. |
| 6 | Frontend | Next.js index, per-agent pages, methodology page, badge embed snippets. Design reference supplied by the owner. |
| 7 | Launch content | First monthly report, methodology published, registry open for contributions. Licensing decided (ADR 0005). |
| 8 | GitHub App (private repos) | Installable app computing the same metrics for an organisation against the public baseline. First paid layer. |

## Non-goals for now

- Judging code quality directly. Outcomes are what we measure.
- Detecting AI code without markers. Out of scope until an approach with published
  precision exists.
- Any vendor-paid placement or scoring.
