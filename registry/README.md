# Attribution registry

`agents.yaml` is the list of AI coding agents HabitusX can detect and the exact markers
each one leaves in commits and pull requests. It is data, not code, so anyone can improve
it with a pull request and every change is reviewed and tested the same way.

## How a signal works

A signal says *where* to look, *what* to match and *how sure* a match makes us.

| Field | Meaning |
|---|---|
| `type` | `trailer_email`, `trailer_name`, `trailer_present`, `author_login`, `author_email`, `author_name`, `message`, `pr_body` |
| `trailer_key` | For trailer types only. The trailer to read, e.g. `Co-Authored-By`. |
| `pattern` | A Python regular expression, searched case-insensitively unless `case_sensitive: true`. |
| `confidence` | `high` if the vendor's tooling writes the marker automatically. `medium` if usually right but reproducible by hand. `low` if merely suggestive. |
| `evidence` | A link to a public commit or vendor documentation showing the marker. Required for `verified`. |

The engine evaluates every signal of every agent. The strongest match decides the
attribution; all matches are kept as evidence. `low` confidence alone never attributes.

## Verification standard

An agent is `verified` when every `high` signal has an `evidence` link to a real,
public example. Until then it is `needs_verification` and the index reports it
separately. `deprecated` agents are kept for historical data but never matched.

## Contributing

1. Edit `agents.yaml`.
2. Run `habitusx registry validate` from `backend/`. It checks the schema, regex validity
   and id uniqueness, and prints a summary.
3. Add a test case in `backend/tests/unit/domain/test_attribution.py` with a redacted
   example of the marker.
4. Open a pull request. CI runs the same validation.

Please do not include real users' names or emails in examples. Bot accounts and vendor
no-reply addresses are fine.

## Schema

`schema.json` is generated from the backend models with `habitusx registry schema`. A
test fails if the committed copy drifts from the code.
