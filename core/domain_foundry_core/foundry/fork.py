"""Fork a FoundrySpec: copy it, give it a new id, and record its parent.

`dump_foundry_spec` refuses to overwrite a spec, so editing one in place is not
a thing you can do. Forking is the sanctioned way to start from an existing
spec: you get a new spec id, and the new spec says which spec it came from.

Three places carry the parentage, so it survives every route out of here:

- `remix.parent_spec` on the spec itself, the field's first writer in the repo.
- one derivation, so the record reads the way every other decision does.
- the generation receipt's `pipeline_version`, which the compiler copies into
  `build-receipt.json`, so a built bundle names the parent too.

Full lineage (history, galleries, "start from this" surfaces) is not here and
is not planned for this release.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from domain_foundry_core.clock import now_iso

from .models import (
    SPEC_ID_PATTERN,
    Derivation,
    FoundrySpec,
    GenerationReceipt,
)

# The build receipt has no field of its own for a parent, and the spec models
# are frozen for this release, so the fork writes the parent into the receipt's
# version string. Readers split on this marker.
FORK_MARKER = "fork-of:"

MAX_USER_DECISIONS = 10


class ForkError(ValueError):
    """A fork that cannot be recorded honestly is refused."""


@dataclass(frozen=True)
class ForkResult:
    spec: FoundrySpec
    parent_id: str

    @property
    def sentence(self) -> str:
        """The one line the CLI prints."""
        return f"Forked {self.parent_id} into {self.spec.id}."


def parent_of(spec: FoundrySpec) -> str | None:
    """The spec this one was forked from, or None if it is not a fork."""
    return spec.remix.parent_spec


def receipt_parent(pipeline_version: str | None) -> str | None:
    """Read the parent back out of a generation receipt's version string."""
    if not pipeline_version or FORK_MARKER not in pipeline_version:
        return None
    tail = pipeline_version.split(FORK_MARKER, 1)[1].strip()
    candidate = tail.split()[0] if tail.split() else ""
    return candidate or None


def fork_spec(
    spec: FoundrySpec,
    new_id: str,
    *,
    title: str | None = None,
    note: str | None = None,
    forked_at: str | None = None,
) -> ForkResult:
    """Copy `spec` under `new_id` and record `spec` as its parent."""

    parent_id = spec.id
    if not re.fullmatch(SPEC_ID_PATTERN, parent_id):
        raise ForkError(
            f"the parent spec id {parent_id!r} cannot be recorded. "
            "A spec id is lowercase letters, numbers and hyphens, "
            "starting with a letter, like 'sourdough-lab'."
        )
    if not re.fullmatch(SPEC_ID_PATTERN, new_id):
        raise ForkError(
            f"{new_id!r} is not a usable spec id. "
            "Give lowercase letters, numbers and hyphens, starting with a "
            "letter, like 'sourdough-rye'."
        )
    if new_id == parent_id:
        raise ForkError(
            f"the fork needs an id different from its parent. Give an id other than {parent_id!r}."
        )
    if spec.remix.parent_spec == new_id:
        raise ForkError(f"{new_id!r} is this spec's own parent. Give the fork a new id instead.")

    stamped_at = forked_at or now_iso()
    decision = note or f"Forked from {parent_id}."

    forked = spec.model_copy(deep=True)
    payload = forked.model_dump(mode="python")
    payload["id"] = new_id
    if title is not None:
        payload["title"] = title
    payload["remix"] = _forked_remix(forked, parent_id, decision)
    payload["derivations"] = [
        *(item.model_dump(mode="python") for item in forked.derivations),
        Derivation(
            output_path="remix.parent_spec",
            decision=f"Started from {parent_id} rather than from nothing.",
            user_decision=decision,
        ).model_dump(mode="python"),
    ]
    payload["generation"] = _forked_receipt(forked.generation, parent_id, stamped_at)

    return ForkResult(spec=FoundrySpec.model_validate(payload), parent_id=parent_id)


def _forked_remix(spec: FoundrySpec, parent_id: str, decision: str) -> dict[str, object]:
    remix = spec.remix.model_dump(mode="python")
    remix["parent_spec"] = parent_id
    decisions = list(remix.get("user_decisions") or [])
    if decision not in decisions:
        decisions.append(decision)
    # The model caps the list. Keeping the fork line means dropping the oldest
    # decision, which loses history, so refuse instead and say why.
    if len(decisions) > MAX_USER_DECISIONS:
        raise ForkError(
            f"{parent_id} already records {MAX_USER_DECISIONS} decisions, "
            "so there is no room to add the fork. Remove one decision from the "
            "parent spec, then fork again."
        )
    remix["user_decisions"] = decisions
    return remix


def _forked_receipt(
    receipt: GenerationReceipt | None, parent_id: str, stamped_at: str
) -> dict[str, object]:
    stamp = f"{FORK_MARKER}{parent_id}"
    if receipt is None:
        # A hand-authored golden carries no receipt. The fork is still a real
        # event, so it gets one that says where it came from and claims nothing
        # about research it did not do.
        return GenerationReceipt(
            origin="manual_golden",
            pipeline_version=stamp,
            generated_at=stamped_at,
            stages=[],
        ).model_dump(mode="python")
    data = receipt.model_dump(mode="python")
    base = str(data.get("pipeline_version") or "").strip()
    base = re.sub(rf"\s*{re.escape(FORK_MARKER)}\S+", "", base).strip()
    data["pipeline_version"] = f"{base} {stamp}".strip()
    data["generated_at"] = stamped_at
    return data


__all__ = [
    "FORK_MARKER",
    "ForkError",
    "ForkResult",
    "fork_spec",
    "parent_of",
    "receipt_parent",
]
