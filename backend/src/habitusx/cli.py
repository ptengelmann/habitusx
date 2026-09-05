"""Command-line interface.

Thin by design: parse arguments, call into the package, print results. No logic lives
here that a test could not reach through the library API.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Annotated

import typer

from habitusx import __version__
from habitusx.config import get_settings
from habitusx.domain.attribution import AttributionInput
from habitusx.domain.reverts import parse_revert
from habitusx.errors import HabitusXError
from habitusx.logging import configure_logging
from habitusx.registry import build_engine, load_registry, registry_json_schema

app = typer.Typer(
    name="habitusx",
    help="HabitusX: the AI Code Outcomes Index.",
    no_args_is_help=True,
    pretty_exceptions_enable=False,
)
registry_app = typer.Typer(help="Inspect and validate the attribution registry.")
app.add_typer(registry_app, name="registry")

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


if __name__ == "__main__":  # pragma: no cover
    app()
