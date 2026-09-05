# ADR 0004: GitHub Archive on BigQuery as the raw source, Postgres for serving, hard cost ceilings

Status: accepted. Date: 2026-09-05.

## Context

The index needs every public push and pull request event, historically and daily. The
GitHub REST API cannot supply that volume. GitHub Archive publishes every public event
as day-partitioned BigQuery tables, free to query within Google's monthly allowance and
cheap beyond it if queries stay partition-scoped. The project must run for a few pounds a
month with no users.

## Decision

- **Raw source:** `githubarchive.day.YYYYMMDD` tables on BigQuery. Queries select only the
  columns the pipeline needs and always name explicit day partitions.
- **Cost guardrails:** every query is dry-run first; if the estimate exceeds
  `HABITUSX_BQ_MAX_BYTES_BILLED` the pipeline raises `QueryBudgetExceededError` and spends
  nothing. The same limit is passed to BigQuery as `maximum_bytes_billed` so the server
  enforces it too.
- **Serving store:** Postgres holds attributed commits, outcomes and daily aggregates.
  The API never touches BigQuery.
- **Append-only:** raw observations and aggregates are versioned by registry and
  methodology version and never overwritten.

## Consequences

- Backfilling history is a deliberate, budgeted operation, not a default.
- Push events carry at most twenty commits and no file paths, so file-level outcomes need
  the GitHub API on a sample (recorded as a limitation in the methodology).
- Postgres hosting choice (Neon, Supabase, Cloud SQL) is deferred to PR 3 and will get
  its own ADR.
