"""Mapping-config models for the generic importer."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field, field_validator


class EntityMapping(BaseModel):
    """One source entity → capture_event + entry + canonical_object."""

    name: str
    domain: str
    object_type: str
    source_ref_template: str
    id_field: str = "id"
    timestamp_field: str = "created_at"
    updated_at_field: str | None = "updated_at"
    raw_text_field: str | None = None
    raw_text_template: str | None = None
    field_map: dict[str, str] = Field(default_factory=dict)
    required_source_fields: list[str] = Field(default_factory=list)
    actor_field: str | None = None
    default_actor: str | None = "importer"

    @field_validator("source_ref_template")
    @classmethod
    def _require_id_placeholder(cls, value: str) -> str:
        if "{id}" not in value and "{" not in value:
            # allow static templates but prefer {id}
            return value
        return value


class MappingConfig(BaseModel):
    """Top-level importer mapping (YAML/JSON)."""

    name: str
    channel: str = "hermes-import"
    entities: list[EntityMapping]
    notes: str | None = None

    @field_validator("channel")
    @classmethod
    def _normalize_channel(cls, value: str) -> str:
        channel = (value or "").strip().lower()
        if not channel:
            raise ValueError("channel is required")
        return channel

    @field_validator("entities")
    @classmethod
    def _require_entities(cls, value: list[EntityMapping]) -> list[EntityMapping]:
        if not value:
            raise ValueError("mapping must declare at least one entity")
        return value


def load_mapping(path: Path | str) -> MappingConfig:
    """Load a mapping config from YAML or JSON."""
    p = Path(path)
    text = p.read_text(encoding="utf-8")
    if p.suffix.lower() in {".yaml", ".yml"}:
        data: Any = yaml.safe_load(text)
    elif p.suffix.lower() == ".json":
        import json

        data = json.loads(text)
    else:
        # try YAML first, then JSON
        try:
            data = yaml.safe_load(text)
        except Exception:
            import json

            data = json.loads(text)
    if not isinstance(data, dict):
        raise ValueError(f"mapping root must be a mapping, got {type(data).__name__}")
    return MappingConfig.model_validate(data)


def render_template(template: str, record: dict[str, Any], *, id_value: Any = None) -> str:
    """Format a template with record fields; `{id}` uses the resolved id."""
    values = dict(record)
    if id_value is not None:
        values["id"] = id_value
    # Missing keys become empty string so partial templates don't crash.
    class _Safe(dict):
        def __missing__(self, key: str) -> str:
            return ""

    return template.format_map(_Safe(values))
