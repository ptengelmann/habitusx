# ADR 0007: Repository panel design and sizing

Status: accepted. Date: 2026-09-05.

## Context

ADR 0006 established that GitHub Archive carries no commit or pull request content after
2025-10-06. GitHub's stated alternative is its REST and GraphQL APIs. Those are rate
limited per account (5,000 GraphQL points per hour), so the ongoing source has to be a
**sample followed over time**, not a census. This ADR records how that sample is drawn,
what is fetched, and the measurements the sizing rests on.

## Measurements (2026-09-05, owner's token)

| Quantity | Measured |
|---|---|
| GraphQL cost per repository, first page of history + 50 recent PRs + metadata | 0.5 points |
| Same, including follow-up history pages for busy repositories | ~1.1 points |
| Requests per hour before hitting the budget | ~4,500 repositories |
| Wall time per repository, sequential, batch of 5 | ~1.5 s |
| GitHub 502 rate on batches of 12 repositories | frequent |
| GitHub 502 rate on batches of 5 | occasional, always recovered on retry |
| Attrition: treated repositories from 2025-09-01 no longer resolving a year later | 18 of 60 (30%) in the first slice; 6 of 12 in the spike |

## Decision

### Cohorts

- **Treated**: repositories with at least one AI-attributed commit in the census
  (Source A). Sampled at a published rate by a stable hash of the lower-cased name.
- **Control**: repositories that received a push on a chosen recent archive day, sampled the
  same way and excluding anything already treated. Repository names are event fields in
  GitHub Archive, not payload, so this remains available after the October 2025 change.
- Sampling is deterministic (`sha256(name) mod 10,000 < rate × 10,000`), so a panel is
  fully reproducible from its definition, and rates can be raised later without
  disturbing existing members.
- Repository names are deduplicated case-insensitively because GitHub treats them so and
  the archive does not normalise them. Found on the first real build.

### Panel v1

Treated rate 0.25 of 6,900 candidates from the one census day on disk, control rate 0.01
of 206,352 repositories active on 2026-08-25. **3,763 repositories: 1,718 treated, 2,045
control.** At the measured cost this is roughly one to two hours of fetching per day on one
token, leaving most of the daily budget free. The panel can grow about tenfold before the
budget binds; a second token or a GitHub App installation raises it further.

### Fetch

Per repository per run, one GraphQL alias returns metadata, default-branch commits since
the watermark (message, author, linked pull request), and the most recently updated pull
requests (author, body, state, timings, review counts). Batches of five repositories per
request; history paginated to a cap of five extra pages, with truncation recorded rather
than hidden. Repositories that no longer resolve are recorded with status `not_found`
and never silently dropped; attrition is a first-class measurement.

Attribution uses the same engine and registry as the census. Commits are attributed from
message trailers and author identity; pull requests from author login, title and body,
for which the registry gained the Claude Code pull request footer signal.

### Output

Three Parquet files per fetch under `panel/fetched_on=YYYY-MM-DD/` (repositories, commits,
pull requests) plus a manifest recording panel version, registry version, methodology
version, points spent and counts by agent and status. Same conventions as the census.

### Budget

The client keeps a reserve of points it never spends and pauses until the hourly reset
when the reserve is reached. Transient failures (429, 502, 503, 504, network) retry with
exponential backoff and jitter; authentication and request errors do not retry.

## Consequences

- From October 2025 onward every published rate is a panel estimate and carries a
  confidence interval and its panel version. The methodology page says so.
- Attrition of around 30% per year among treated repositories means the treated cohort
  must be refreshed from newer census days and, later, from the panel's own control
  cohort as it observes AI adoption. Panel versions make that auditable.
- Default-branch history misses feature-branch work that never merges; pull requests
  cover the merged part. Documented as a limitation.
- Fetching is sequential today. Parallel batches are a straightforward later optimisation
  once the daily run exists (PR 4 territory, alongside scheduling).

## First run (2026-09-05, first 60 members, since 2026-08-29)

42 repositories found, 18 gone. 956 commits, 210 attributed, all at high confidence
(Claude Code 175, Cursor 19, Copilot 16). 191 pull requests, 101 merged, 8 attributed to
Claude Code via the PR footer. 67 points, 19 requests, 91 seconds.
