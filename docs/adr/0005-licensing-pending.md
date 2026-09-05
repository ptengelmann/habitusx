# ADR 0005: Licensing

Status: proposed, decision needed from the owner. Date: 2026-09-05.

## Context

The repository is public from day one. The registry is intended to accept public contributions,
and the index will publish numbers people cite. Licensing affects both contributions and
acquirability, so it should be decided deliberately rather than defaulted.

## Options

| Component | Option A (open) | Option B (source-available) | Option C (closed) |
|---|---|---|---|
| Backend code | Apache-2.0 | BSL 1.1 converting to Apache-2.0 after 3 years | Proprietary |
| Registry data | CC-BY-4.0 (attribution required) | CC-BY-4.0 | Proprietary |
| Published aggregates | CC-BY-4.0 | CC-BY-4.0 | Terms of use |

## Recommendation

Registry data as CC-BY-4.0 regardless of the code decision: contributors will not send
rules to a dataset they cannot reuse, and attribution back to HabitusX is the distribution
loop. Code under BSL 1.1 keeps the option of a hosted business while letting people read
and audit the methodology, which is the product's credibility. Decide before accepting
outside contributions (PR 6).

## Decision

Pending.
