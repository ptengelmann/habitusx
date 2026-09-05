"""Command-line interface.

Thin by design: parse arguments, call into the package, print results. No logic lives
here that a test could not reach through the library API.
"""

from __future__ import annotations

import json
import sys
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Annotated

import typer

from habitusx import __version__
from habitusx.adapters.bigquery import BigQueryGateway, make_client
from habitusx.adapters.github import GitHubGraphQL, HttpxTransport
from habitusx.adapters.github.client import TokenSource
from habitusx.config import Settings, get_settings
from habitusx.domain.attribution import AttributionInput
from habitusx.domain.reverts import parse_revert
from habitusx.errors import ConfigurationError, HabitusXError
from habitusx.logging import configure_logging
from habitusx.registry import build_engine, load_registry, registry_json_schema
from habitusx.services.ingest import estimate_day, ingest_day
from habitusx.services.panel import (
    assemble_panel,
    control_candidates,
    fetch_panel,
    load_panel,
    save_panel,
    treated_candidates,
)

app = typer.Typer(
    name="habitusx",
    help="HabitusX: the AI Code Outcomes Index.",
    no_args_is_help=True,
    pretty_exceptions_enable=False,
)
registry_app = typer.Typer(help="Inspect and validate the attribution registry.")
app.add_typer(registry_app, name="registry")
ingest_app = typer.Typer(help="Pull days of GitHub Archive into attributed observations.")
app.add_typer(ingest_app, name="ingest")
panel_app = typer.Typer(help="Build and fetch the repository panel (ongoing source, ADR 0006).")
app.add_typer(panel_app, name="panel")

RegistryOption = Annotated[
    Path | None,
    typer.Option("--registry", "-r", help="Path to agents.yaml. Defaults to the repo copy."),
]


@app.callback()
def _setup() -> None:
    settings = get_settings()
    configure_logging(settings.log_level, settings.effective_log_format)


@app.command()
def version() -> None:
    """Print the installed version."""
    typer.echo(__version__)


@registry_app.command("validate")
def registry_validate(registry: RegistryOption = None) -> None:
    """Validate the registry file and summarise its contents."""
    path = registry or get_settings().registry_path
    try:
        loaded = load_registry(path)
    except HabitusXError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc
    signal_count = sum(len(agent.signals) for agent in loaded.agents)
    typer.echo(f"OK: {path}")
    typer.echo(f"  version {loaded.version}, {len(loaded.agents)} agents, {signal_count} signals")
    for agent in loaded.agents:
        typer.echo(f"  - {agent.id:<22} {agent.status.value:<20} {len(agent.signals)} signals")


@registry_app.command("schema")
def registry_schema() -> None:
    """Print the JSON Schema for the registry file."""
    sys.stdout.write(registry_json_schema())


@app.command()
def attribute(
    message_file: Annotated[
        Path | None,
        typer.Option("--message-file", "-m", help="Read the commit message from this file."),
    ] = None,
    author_login: Annotated[str | None, typer.Option()] = None,
    author_email: Annotated[str | None, typer.Option()] = None,
    author_name: Annotated[str | None, typer.Option()] = None,
    registry: RegistryOption = None,
) -> None:
    """Attribute one commit message (from --message-file or stdin) and print JSON."""
    message = message_file.read_text(encoding="utf-8") if message_file else sys.stdin.read()
    path = registry or get_settings().registry_path
    try:
        engine = build_engine(path)
    except HabitusXError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc

    item = AttributionInput(
        message=message,
        author_login=author_login,
        author_email=author_email,
        author_name=author_name,
    )
    result = engine.attribute(item)
    revert = parse_revert(message)
    payload = {
        "attribution": result.model_dump(mode="json") if result else None,
        "revert": revert.model_dump(mode="json") if revert else None,
    }
    typer.echo(json.dumps(payload, indent=2))


def _parse_day(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        typer.echo(f"DAY must be YYYY-MM-DD, got {value!r}", err=True)
        raise typer.Exit(code=2) from exc


def _gateway(settings: Settings, max_bytes: int | None) -> BigQueryGateway:
    """Build the real gateway, or fail with instructions if the project is not configured."""
    if not settings.gcp_project:
        raise ConfigurationError(
            "HABITUSX_GCP_PROJECT is not set. Put it in backend/.env, e.g. "
            "HABITUSX_GCP_PROJECT=habitusx-507702, and make sure you have run "
            "'gcloud auth application-default login'."
        )
    return BigQueryGateway(
        make_client(settings.gcp_project, settings.bq_location),
        max_bytes_billed=max_bytes or settings.bq_max_bytes_billed,
        location=settings.bq_location,
    )


def _human_bytes(n: int) -> str:
    return f"{n / 1024**3:,.2f} GiB"


@ingest_app.command("estimate")
def ingest_estimate(
    day: Annotated[str, typer.Argument(help="UTC day, YYYY-MM-DD")],
    registry: RegistryOption = None,
) -> None:
    """Dry-run the extraction for DAY and print the bytes it would scan. Spends nothing."""
    parsed = _parse_day(day)
    settings = get_settings()
    try:
        loaded = load_registry(registry or settings.registry_path)
        gateway = _gateway(settings, None)
        estimated = estimate_day(parsed, registry=loaded, gateway=gateway)
    except HabitusXError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc
    verdict = "within" if estimated <= gateway.max_bytes_billed else "OVER"
    typer.echo(
        f"{day}: {_human_bytes(estimated)} estimated, {verdict} the "
        f"{_human_bytes(gateway.max_bytes_billed)} ceiling"
    )


@ingest_app.command("day")
def ingest_one_day(
    day: Annotated[str, typer.Argument(help="UTC day, YYYY-MM-DD")],
    out: Annotated[
        Path | None, typer.Option("--out", help="Output root. Defaults to HABITUSX_DATA_DIR.")
    ] = None,
    max_bytes: Annotated[
        int | None,
        typer.Option("--max-bytes", help="Override the per-query byte ceiling for this run."),
    ] = None,
    registry: RegistryOption = None,
) -> None:
    """Extract DAY from GitHub Archive, attribute it, and write Parquet plus a manifest."""
    parsed = _parse_day(day)
    settings = get_settings()
    try:
        loaded = load_registry(registry or settings.registry_path)
        gateway = _gateway(settings, max_bytes)
        summary = ingest_day(
            parsed, registry=loaded, gateway=gateway, out_dir=out or settings.data_dir
        )
    except HabitusXError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc

    typer.echo(f"{summary.day}: {summary.rows_total:,} rows -> {summary.output_path}")
    typer.echo(
        f"  attributed {summary.rows_attributed:,}   reverts {summary.rows_reverts:,}   "
        f"baseline {summary.rows_baseline:,}   skipped {summary.rows_skipped_invalid:,}"
    )
    for agent_id, count in sorted(summary.by_agent.items(), key=lambda kv: -kv[1]):
        typer.echo(f"  {agent_id:<20} {count:>8,}")
    typer.echo(
        f"  billed {_human_bytes(summary.stats.billed_bytes)} in "
        f"{summary.stats.elapsed_seconds:.1f}s   manifest {summary.manifest_path.name}"
    )


def _github_client(settings: Settings) -> GitHubGraphQL:
    token = TokenSource(env_token=settings.github_token).resolve()
    return GitHubGraphQL(HttpxTransport(token), reserve_points=settings.github_reserve_points)


@panel_app.command("build")
def panel_build(  # noqa: PLR0917 - typer options map one-to-one onto parameters
    control_day: Annotated[
        str, typer.Option("--control-day", help="Archive day to draw active repos from, YYYY-MM-DD")
    ],
    version: Annotated[int, typer.Option("--version", min=1)] = 1,
    treated_rate: Annotated[float, typer.Option("--treated-rate", min=0.0, max=1.0)] = 0.25,
    control_rate: Annotated[float, typer.Option("--control-rate", min=0.0, max=1.0)] = 0.01,
    observations: Annotated[
        Path | None,
        typer.Option("--observations", help="Census output root. Defaults to data dir."),
    ] = None,
    out: Annotated[Path | None, typer.Option("--out", help="Panel JSON path.")] = None,
) -> None:
    """Build a panel: treated repos from the census on disk, control repos from the archive."""
    day = _parse_day(control_day)
    settings = get_settings()
    obs_root = (observations or settings.data_dir) / "observations"
    target = out or settings.data_dir / "panel" / f"panel_v{version}.json"
    try:
        gateway = _gateway(settings, None)
        treated = treated_candidates(obs_root)
        control = control_candidates(day, gateway=gateway)
        panel = assemble_panel(
            version=version,
            created_on=datetime.now(UTC).date(),
            treated=treated,
            control=control,
            treated_rate=treated_rate,
            control_rate=control_rate,
            control_source=f"archive_active:{day.isoformat()}",
        )
        save_panel(panel, target)
    except HabitusXError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc
    n_treated = sum(1 for m in panel.members if m.cohort.value == "treated")
    typer.echo(f"panel v{panel.version}: {len(panel.members):,} repos -> {target}")
    typer.echo(f"  treated {n_treated:,} of {len(treated):,} candidates at rate {treated_rate}")
    n_control = len(panel.members) - n_treated
    typer.echo(
        f"  control {n_control:,} of {len(control):,} active on {day} at rate {control_rate}"
    )


@panel_app.command("fetch")
def panel_fetch(
    since: Annotated[
        str, typer.Option("--since", help="Fetch activity since this UTC day, YYYY-MM-DD")
    ],
    panel: Annotated[
        Path | None, typer.Option("--panel", help="Panel JSON. Defaults to latest v1.")
    ] = None,
    limit: Annotated[
        int | None, typer.Option("--limit", min=1, help="Only the first N members.")
    ] = None,
    out: Annotated[
        Path | None, typer.Option("--out", help="Output root. Defaults to data dir.")
    ] = None,
    registry: RegistryOption = None,
) -> None:
    """Fetch every panel member's commits and pull requests since a date via the GitHub API."""
    since_day = _parse_day(since)
    settings = get_settings()
    panel_path = panel or settings.data_dir / "panel" / "panel_v1.json"
    try:
        loaded_registry = load_registry(registry or settings.registry_path)
        loaded_panel = load_panel(panel_path)
        client = _github_client(settings)
        summary = fetch_panel(
            loaded_panel,
            client=client,
            registry=loaded_registry,
            since=datetime(since_day.year, since_day.month, since_day.day, tzinfo=UTC),
            fetched_on=datetime.now(UTC).date(),
            out_dir=out or settings.data_dir,
            limit=limit,
            batch_size=settings.panel_batch_size,
        )
    except HabitusXError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc

    typer.echo(
        f"{summary.fetched_on}: {summary.repos_requested:,} repos since {since} "
        f"-> {summary.output_dir}"
    )
    statuses = ", ".join(f"{k} {v:,}" for k, v in summary.repos_by_status.items())
    typer.echo(f"  repos: {statuses}")
    typer.echo(
        f"  commits {summary.commits:,} (attributed {summary.commits_attributed:,}, "
        f"reverts {summary.reverts:,})   pulls {summary.pulls:,} "
        f"(attributed {summary.pulls_attributed:,})"
    )
    for agent_id, count in sorted(summary.commits_by_agent.items(), key=lambda kv: -kv[1]):
        typer.echo(f"  {agent_id:<20} {count:>8,} commits")
    typer.echo(f"  github: {summary.points_spent:,} points in {summary.requests_made:,} requests")


if __name__ == "__main__":  # pragma: no cover
    app()
