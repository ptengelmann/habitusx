# ADR 0006: Two-stage ingest, and the October 2025 Events API change

Status: accepted. Date: 2026-09-05.

## Context

PR 2 built the first ingest: one UTC day of GitHub Archive push events, filtered in SQL
by a prefilter compiled from the attribution registry, then attributed precisely in Python
and written as Parquet with a manifest. On the first run against a recent day it returned
zero rows. Investigation established the following facts, each verified by query against
`githubarchive.day.*` on 2026-09-05:

1. **On 2025-10-07 GitHub changed the Events API** (announced in the GitHub changelog on
   2025-08-08). Push event payloads lost their commit lists and now contain only
   `repository_id`, `push_id`, `ref`, `head` and `before`. Pull request payloads were
   reduced to `action`, `number` and a `pull_request` object holding only `id`, `number`,
   `url`, `base` and `head`. No author, title, body, merge state or language.
2. GitHub Archive mirrors that API, so from 2025-10-07 onward it contains **no commit
   messages, no trailers, no PR bodies and no PR outcomes**. Day tables before the change
   average 16 GiB; after it, under 1 GiB.
3. **GitHub Archive's completeness has also degraded in 2026.** 2025-09-01 has 3.77M
   events. 2026-08-31 has 1.25M with 13.5K pull request events against a 2025 norm of
   350K to 450K. 2026-09-04 has 547K pull request events and zero pushes. The collector is
   evidently struggling with the new API.
4. Google's `bigquery-public-data.github_repos.commits` mirror does hold full messages but
   was last refreshed 2025-10-14 and is 910 GB. Stale and too expensive to scan routinely.
5. The only other public tracker of AI-attributed commits, botcommits.dev, hit the same
   wall in October 2025 and fell back to GitHub Search API estimates, which its own
   methodology page says drift 10 to 15 percent between calls.

GitHub's stated position is that removed fields "can be retrieved through the standard
REST API" using the identifiers that remain.

## Decision

The index is fed from two sources with different roles.

### Source A: GitHub Archive, historical, commit level (2011-02-12 to 2025-10-06)

The PR 2 pipeline as built. Complete population of public pushes, full commit messages,
full revert detection. This covers the first eight months of Claude Code, the Copilot
coding agent's launch, Cursor, Devin and the rest. It is the historical baseline and is
frozen: reverts of a September 2025 commit that happened after 2025-10-06 are invisible,
which the methodology must state.

`commits_for_day` refuses days after `PUSH_COMMITS_LAST_DAY` with an error that points
here, so nobody spends money on empty scans.

### Source B: a repository panel enriched through the GitHub API (2025-10-07 onward)

Since full-population content is no longer public, the ongoing index becomes a **panel**:
a deterministic sample of public repositories followed over time, with commit and pull
request details fetched from the GitHub REST or GraphQL API. This is how audience
measurement works when the full population is not observable.

Design constraints for PR 3:

- **Panel selection** is deterministic and documented: repositories with at least one
  AI-attributed commit in Source A form the treated cohort; a hash-sampled random cohort of
  active repositories forms the control. Both refresh on a published schedule.
- **Enrichment** fetches, per panel repository per day, the commits since the last
  observation (messages, authors, trailers) and pull requests updated since the last
  observation (author, body, merged state, review counts). GraphQL batching keeps this
  inside one account's rate budget for a panel of tens of thousands of repositories.
- **Within-repo baselines** are preserved by construction, because whole repositories are
  sampled, not individual commits.
- **Identifiers from GitHub Archive** (repository ids, push heads, PR numbers) are used to
  detect activity cheaply where the archive is complete, and never relied on where it is
  not.
- Every published number carries its source (A or B), its panel version and its
  registry version.

### What we do not do

- Estimate volumes from the GitHub Search API. Its counts are approximate and unstable.
- Scan `github_repos.commits` routinely.
- Present Source A and Source B numbers as one continuous series without saying so.

## Consequences

- The "continuous index" is continuous, but from October 2025 it is a measured sample with
  confidence intervals rather than a full census. That is a stronger statistical position
  than the alternatives available to anyone else, and it must be explained plainly.
- PR 3 is the GitHub API adapter and the panel, not the Postgres store. Postgres moves to
  PR 4. The roadmap is updated.
- A GitHub token with public-repo read scope is needed for Source B. The owner's existing
  `gh` login provides one for development.
- The pipeline's two-stage shape (cheap coarse filter, precise Python attribution) is
  unchanged and applies to both sources.

## Verification on 2025-09-01

Ingesting that day end to end: 92,158 rows kept from 3.06M commits, 30,051 attributed
across six agents (Claude Code 17,344; Copilot 8,436; Cursor 3,843; Aider 228; Devin 117;
OpenHands 83), 4,180 reverts, 57,767 within-repo baseline commits, 14.8 GiB billed,
81 seconds. Cursor, Aider and OpenHands trailer signals were promoted to `verified` on the
strength of this run.
