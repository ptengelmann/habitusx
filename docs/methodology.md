# Methodology (draft)

This page will be published alongside the index. Numbers without a method are marketing.

## What is measured

For every commit and pull request in public GitHub repositories that carries a
recognisable AI coding agent marker, HabitusX records what happened next.

| Metric | Definition | Source |
|---|---|---|
| Revert rate | Share of attributed commits later undone by a revert commit within 30 days | Revert parser joined on SHA or PR number |
| PR acceptance | Share of attributed pull requests merged rather than closed | PullRequestEvent |
| Time to merge | Hours from PR open to merge, median | PullRequestEvent |
| Review burden | Review comments per PR, median | PullRequestReviewCommentEvent |
| Follow-up fix rate | Share of attributed commits followed within 14 days by a commit touching the same files with a fix-like message | GitHub API, sampled |

Each metric is reported for the attributed population and for the human-authored baseline
**in the same repositories over the same period**, so a repository's own culture of
reverting or reviewing does not masquerade as an agent effect.

## Attribution

Agents are detected from markers their tooling writes: co-author trailers, bot account
logins, task links in PR descriptions. The full rule set is public in
`registry/agents.yaml`, versioned, and every attribution stores the evidence that
produced it. Rules are marked `verified` only when backed by a public example.

Confidence levels: `high` means the vendor's tooling writes the marker automatically;
`medium` means usually correct but reproducible by hand; `low` is reported as evidence
but never sufficient alone.

## What this cannot tell you

- **Coverage is partial.** Agents that leave no marker, and users who disable markers,
  are invisible. The index publishes its estimated coverage per agent and treats it as a
  first-class number, not a footnote.
- **Reverts are not quality.** A revert can mean a bug, a change of plan, or a merge
  mistake. Across thousands of commits the noise averages out; for any one repository it
  may not.
- **Selection effects exist.** Repositories that adopt agents early differ from those that
  do not. Within-repo baselines reduce this; they do not eliminate it.
- **Squash merges hide commits.** When a PR is squash-merged, the individual commits and
  their trailers are replaced by one commit whose message GitHub composes from the PR.
  Trailers usually survive in the body; the pipeline reads them there.

## Two sources, stated on every number

GitHub changed its public Events API on 7 October 2025 and removed commit and pull request
content from the events that GitHub Archive mirrors. HabitusX therefore has two sources
and never blends them silently:

- **Source A, census, 2011 to 6 October 2025.** Every public push, full commit messages.
  Reverts that happened after 6 October 2025 are not visible in this source.
- **Source B, panel, 7 October 2025 onward.** A deterministic sample of public
  repositories followed through the GitHub API, with confidence intervals on every rate.
  Cohorts, sampling and sizing are in ADR 0007. Repository attrition (deleted, private,
  renamed) is measured and published, not hidden.

The full reasoning is in ADR 0006.

## Reproducibility

Every published number is tied to a registry version, a methodology version and a date
range. Re-running the pipeline with the same three produces the same number.
