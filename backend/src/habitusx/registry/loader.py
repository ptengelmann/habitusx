"""Read ``registry/agents.yaml`` into a validated :class:`Registry`.

Validation errors are turned into a :class:`RegistryValidationError` whose message lists
every problem with its location in the file, so a contributor fixing the registry never
has to read a pydantic traceback.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

import yaml
from pydantic import ValidationError

from habitusx.domain.attribution import AttributionEngine, Registry
from habitusx.errors import RegistryError, RegistryValidationError

if TYPE_CHECKING:
    from pathlib import Path


def load_registry(path: Path) -> Registry:
    """Load and validate the registry at ``path``.

    Raises:
        RegistryError: if the file cannot be read or is not YAML.
        RegistryValidationError: if the content does not satisfy the schema.
    """
    try:
        raw_text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise RegistryError(f"cannot read registry at {path}: {exc}") from exc

    try:
        data: Any = yaml.safe_load(raw_text)
    except yaml.YAMLError as exc:
        raise RegistryError(f"registry at {path} is not valid YAML: {exc}") from exc

    if not isinstance(data, dict):
        raise RegistryValidationError(str(path), ["top level must be a mapping"])

    try:
        return Registry.model_validate(data)
    except ValidationError as exc:
        raise RegistryValidationError(str(path), _describe(exc)) from exc


def build_engine(path: Path) -> AttributionEngine:
    """Convenience: load the registry at ``path`` and wrap it in an engine."""
    return AttributionEngine(load_registry(path))


def registry_json_schema() -> str:
    """The JSON Schema for the registry file, as a stable, indented string.

    Committed to ``registry/schema.json`` so editors can validate as contributors type.
    A test asserts the committed copy matches this output.
    """
    schema = Registry.model_json_schema()
    schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
    schema["$id"] = "https://habitusx.dev/schemas/registry.json"
    return json.dumps(schema, indent=2, sort_keys=True) + "\n"


def _describe(exc: ValidationError) -> list[str]:
    problems: list[str] = []
    for error in exc.errors():
        location = ".".join(str(part) for part in error["loc"]) or "<root>"
        problems.append(f"{location}: {error['msg']}")
    return problems
