"""Write an approved look back into the spec file it came from.

The spec on disk is the working copy. `bind_look` sets its `look` field, checks
the whole spec still validates, and replaces the file in one move, so a failed
write never leaves half a spec behind.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from domain_foundry_core.foundry.models import FoundrySpec, LookBinding

from .marks import plain_reason


class BindingError(ValueError):
    """A spec we cannot bind to, with a sentence a person can act on."""


def load_spec_document(path: Path) -> dict[str, Any]:
    """Read a spec YAML file as a plain mapping."""

    if not path.exists():
        raise BindingError(f"There is no spec at {path}.")
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as error:
        raise BindingError(f"{path} is not readable as YAML: {error}") from error
    if not isinstance(data, dict):
        raise BindingError(f"{path} does not hold a spec.")
    return data


def write_spec_document(path: Path, document: dict[str, Any]) -> None:
    """Replace a spec file in one move, or leave the old one exactly as it was."""

    payload = yaml.safe_dump(document, sort_keys=False, allow_unicode=True)
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except Exception:
        Path(temporary).unlink(missing_ok=True)
        raise


def bind_look(path: Path, binding: LookBinding) -> FoundrySpec:
    """Put the approved look into the spec at `path` and save it.

    Returns the validated spec that is now on disk.
    """

    document = load_spec_document(path)
    document["look"] = binding.model_dump(mode="json", exclude_none=True)
    try:
        spec = FoundrySpec.model_validate(document)
    except ValidationError as error:
        raise BindingError(f"That look does not fit this spec. {plain_reason(error)}") from error
    concept_ids = {concept.id for concept in spec.concepts}
    if binding.concept_id and binding.concept_id not in concept_ids:
        raise BindingError(
            f"This spec has no concept called {binding.concept_id!r}. "
            f"Its concepts are: {', '.join(sorted(concept_ids))}."
        )
    write_spec_document(path, document)
    return spec


__all__ = ["BindingError", "bind_look", "load_spec_document", "write_spec_document"]
