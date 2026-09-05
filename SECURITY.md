# Security policy

## Reporting a vulnerability

Please do not open a public issue for security problems.

Use GitHub's private vulnerability reporting on this repository
(Security tab, "Report a vulnerability"). You will get an acknowledgement within
five working days and a fix or a clear plan within thirty.

## Scope

- The backend pipeline and API in this repository.
- The published index and badge endpoints once they exist.

Out of scope: GitHub Archive and BigQuery themselves, and third-party services we consume.

## Data handling

HabitusX reads only events GitHub already publishes for public repositories. Author
identities are used solely to evaluate attribution rules and are stored hashed, never in
the clear, in any table the API can reach.
