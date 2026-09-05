# ADR 0001: Monorepo with backend, frontend and registry at the root

Status: accepted. Date: 2026-09-05.

## Context

The product has a data pipeline and API (Python), a public website (TypeScript), and a
community-contributed dataset (YAML). They ship together and change together early on.

## Decision

One repository. `backend/` and `frontend/` are independent projects with their own
toolchains and CI jobs. `registry/` sits at the root because it is language-neutral data
that both the backend reads and external contributors edit; burying it inside `backend/`
would make it look like implementation detail. `docs/` holds architecture, methodology,
roadmap and ADRs.

## Consequences

- One PR can change a registry rule, the code that reads it and the docs that describe it.
- CI is per-directory; a frontend change does not run the Python gate and vice versa
  (path filters arrive with the frontend PR).
- If the frontend later needs its own release cadence, it can be split out without
  touching the backend.
