"""Command-line interface.

Thin by design: parse arguments, call into the package, print results. No logic lives
here that a test could not reach through the library API.
"""

from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path
from typing import Annotated

import typer

from habitusx import __version__
from habitusx.adapters.bigquery import BigQueryGateway, make_client
from habitusx.config import Settings, get_settings
from habitusx.domain.attribution import AttributionInput
from habitusx.domain.reverts import parse_revert
from habitusx.errors import ConfigurationError, HabitusXError
from habitusx.logging import configure_logging
from habitusx.registry import build_engine, load_registry, registry_json_schema
from habitusx.services.ingest import estimate_day, ingest_day

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


if __name__ == "__main__":  # pragma: no cover
    app()
