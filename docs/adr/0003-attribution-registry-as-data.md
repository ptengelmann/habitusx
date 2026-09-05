# ADR 0003: Attribution rules are data, not code

Status: accepted. Date: 2026-09-05.

## Context

Which AI agents exist and what markers they leave changes monthly. The set of people who
know a given agent's markers is wider than the set of people who will read Python. The
registry is also the community-contributable part of the product and part of its moat.

## Decision

Detection rules live in `registry/agents.yaml`. Each agent has signals with a type
(trailer email/name/presence, author login/email/name, message, PR body), a regular
expression, a confidence level and evidence. The backend validates the file against
pydantic models, generates `registry/schema.json` from them, and a test fails if the
committed schema drifts. The engine is generic: it evaluates every signal and reports the
strongest match with all evidence.

Confidence semantics are fixed: `high` is written automatically by vendor tooling,
`medium` is usually right but reproducible by hand, `low` is evidence only and never
attributes alone. Agents are `verified` only when every high signal has a public example.

## Consequences

- Adding an agent is a YAML edit plus a test case; no Python knowledge required.
- Every stored attribution records the registry version, so results can be recomputed
  when rules change and the two versions compared.
- The engine cannot express rules that need cross-field logic ("login X *and* trailer Y").
  If that becomes necessary, add a composite signal type rather than special-casing.
