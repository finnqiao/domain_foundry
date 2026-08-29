"""The marks a person leaves on a review page, and how they become a binding.

The review page is a static HTML file. It cannot write to your disk, so its
Save button hands you a `review-marks.json` file. This module is the contract
for that file: what it may contain, what a bad one is told, and how a good one
turns into the `LookBinding` the build reads.

## The marks file, field by field

```json
{
  "marks_version": "review-marks/1",
  "look_id": "sourdough-lab-look-1",
  "chosen_concept": "bake-bench",
  "concepts": {
    "bake-bench": {
      "topology": "workflow",
      "typography_stack": "reading_serif",
      "density_scale": "bench",
      "token_overrides": {"accent": "#E39A2D"},
      "signature_elements": ["progress_bar"],
      "pins": [{"x": 12.5, "y": 40.0, "text": "the timer should be first"}],
      "borrow": null,
      "borrow_reason": null,
      "notes": ["keep the crumb photo big"]
    }
  },
  "notes": ["I want to open this at 6am with one hand"],
  "saved_at": "2026-08-28T09:12:00Z"
}
```

Everything except `marks_version`, `look_id`, and `concepts` is optional. A page
you only half marked up still binds what it does say.

## What becomes what

- `chosen_concept` becomes `LookBinding.concept_id`.
- The chosen concept's topology, type stack, density, colours, and signature
  elements become the binding's.
- A `borrow` written on any other concept becomes a `BorrowedFragment`.
- Pins and notes become plain sentences in `LookBinding.notes`, with the pin's
  position said in words, because a build has no pixels to hang a dot on.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from domain_foundry_core.foundry.models import (
    BorrowedFragment,
    DensityScale,
    LookBinding,
    NavigationTopology,
    SignatureElement,
    TypographyStack,
    UserText,
    VisualTokens,
)

MARKS_VERSION = "review-marks/1"
MARKS_FILENAME = "review-marks.json"

_HEX = re.compile(r"#[0-9A-Fa-f]{6}")


class MarksError(ValueError):
    """A marks file we cannot use, with a sentence a person can act on."""


class MarkPin(BaseModel):
    """A note pinned to a spot on one preview."""

    model_config = ConfigDict(extra="forbid")

    x: float = Field(ge=0, le=100)
    y: float = Field(ge=0, le=100)
    text: UserText


class ConceptMarks(BaseModel):
    """Everything marked on one concept card."""

    model_config = ConfigDict(extra="forbid")

    topology: NavigationTopology | None = None
    typography_stack: TypographyStack | None = None
    density_scale: DensityScale | None = None
    token_overrides: dict[str, str] = Field(default_factory=dict, max_length=20)
    signature_elements: list[SignatureElement] = Field(default_factory=list, max_length=5)
    pins: list[MarkPin] = Field(default_factory=list, max_length=20)
    borrow: str | None = Field(default=None, max_length=2_000)
    borrow_reason: str | None = Field(default=None, max_length=2_000)
    notes: list[str] = Field(default_factory=list, max_length=20)


class ReviewMarks(BaseModel):
    """A whole marked-up review page."""

    model_config = ConfigDict(extra="forbid")

    marks_version: Literal["review-marks/1"] = MARKS_VERSION
    look_id: str = Field(min_length=1, max_length=120)
    chosen_concept: str | None = Field(default=None, max_length=120)
    concepts: dict[str, ConceptMarks] = Field(default_factory=dict, max_length=10)
    notes: list[str] = Field(default_factory=list, max_length=40)
    saved_at: str | None = Field(default=None, max_length=40)

    def to_binding(self) -> LookBinding:
        """Turn the marks into the binding the build reads.

        Raises `MarksError` when nothing is chosen, because a build cannot pick
        for you.
        """

        if not self.chosen_concept:
            raise MarksError(
                "Nothing is chosen yet. Open the review page, pick one of the concepts "
                "under 'Which one should we build?', press Save, then run this again."
            )
        if self.chosen_concept not in self.concepts:
            known = ", ".join(sorted(self.concepts)) or "none"
            raise MarksError(
                f"The chosen concept {self.chosen_concept!r} is not on this page. "
                f"The concepts on it are: {known}."
            )
        chosen = self.concepts[self.chosen_concept]
        borrowed: list[BorrowedFragment] = []
        for concept_id, marks in self.concepts.items():
            piece = (marks.borrow or "").strip()
            if not piece or concept_id == self.chosen_concept:
                continue
            reason = (marks.borrow_reason or "").strip() or None
            borrowed.append(BorrowedFragment(from_concept=concept_id, piece=piece, reason=reason))
        notes = [line.strip() for line in self.notes if line.strip()]
        for concept_id, marks in self.concepts.items():
            for line in marks.notes:
                text = line.strip()
                if text:
                    notes.append(f"On {concept_id}: {text}")
            for pin in marks.pins:
                notes.append(f"On {concept_id}, {_where(pin)}: {pin.text.strip()}")
        try:
            return LookBinding(
                look_id=self.look_id,
                concept_id=self.chosen_concept,
                topology=chosen.topology,
                typography_stack=chosen.typography_stack,
                density_scale=chosen.density_scale,
                token_overrides=dict(chosen.token_overrides),
                signature_elements=list(chosen.signature_elements),
                borrowed_fragments=borrowed[:10],
                notes=notes[:40],
                approved_at=self.saved_at,
            )
        except ValidationError as error:
            raise MarksError(plain_reason(error)) from error


def _where(pin: MarkPin) -> str:
    """Say a pin's position in words. A build has no pixels to hang a dot on."""

    across = "left" if pin.x < 34 else ("middle" if pin.x < 67 else "right")
    down = "top" if pin.y < 34 else ("middle" if pin.y < 67 else "bottom")
    if across == "middle" and down == "middle":
        return "in the middle"
    if across == "middle":
        return f"{down} of the page"
    if down == "middle":
        return f"the {across} side"
    return f"{down} {across}"


_FIELD_WORDS: dict[str, str] = {
    "look_id": "which page these marks came from",
    "chosen_concept": "which concept you picked",
    "marks_version": "the version line",
    "token_overrides": "a colour you set",
    "concepts": "the per concept marks",
    "pins": "a pinned note",
    "notes": "a note",
    "topology": "the layout choice",
    "typography_stack": "the type choice",
    "density_scale": "the spacing choice",
    "signature_elements": "a signature piece",
}


def plain_reason(error: ValidationError) -> str:
    """One sentence a person can act on, built from the first problem found."""

    problems = error.errors()
    if not problems:
        return "That marks file does not match what a review page saves."
    first = problems[0]
    location = ".".join(str(part) for part in first.get("loc", ()) if part != "__root__")
    label = _FIELD_WORDS.get(location.split(".")[0], location or "one of the fields")
    message = str(first.get("msg", "")).strip()
    if message.lower().startswith("value error, "):
        message = message[len("value error, ") :]
    return f"That marks file has a problem with {label}: {message}."


def parse_marks(payload: Any) -> ReviewMarks:
    """Validate already-loaded marks, with a plain message when they are wrong."""

    if not isinstance(payload, dict):
        raise MarksError(
            "A marks file holds one JSON object. This one holds something else. "
            "Press Save on the review page and use the file it hands you."
        )
    try:
        return ReviewMarks.model_validate(payload)
    except ValidationError as error:
        raise MarksError(plain_reason(error)) from error


def read_marks(path: Path) -> ReviewMarks:
    """Load and validate a marks file from disk."""

    if not path.exists():
        raise MarksError(
            f"There are no marks at {path}. Open the review page, mark it up, press Save, "
            "and move the downloaded file to that spot, or point at it with --marks."
        )
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise MarksError(
            f"{path} is not valid JSON ({error.msg} on line {error.lineno}). "
            "Press Save on the review page again and use the file it hands you."
        ) from error
    return parse_marks(raw)


def marks_from_choice(
    *,
    look_id: str,
    concept_id: str,
    token_overrides: dict[str, str] | None = None,
    topology: str | None = None,
    typography_stack: str | None = None,
    density_scale: str | None = None,
    signature_elements: list[str] | None = None,
    notes: list[str] | None = None,
    saved_at: str | None = None,
) -> ReviewMarks:
    """Build the same marks a browser would save, from command line flags.

    This is what keeps the page and the terminal equal. Anything the page can
    say, a flag can say, and both end in the same binding.
    """

    payload: dict[str, Any] = {
        "marks_version": MARKS_VERSION,
        "look_id": look_id,
        "chosen_concept": concept_id,
        "concepts": {
            concept_id: {
                "topology": topology,
                "typography_stack": typography_stack,
                "density_scale": density_scale,
                "token_overrides": dict(token_overrides or {}),
                "signature_elements": list(signature_elements or []),
                "notes": list(notes or []),
            }
        },
        "saved_at": saved_at,
    }
    return parse_marks(payload)


def check_token_overrides(overrides: dict[str, str]) -> None:
    """Raise `MarksError` with a plain sentence when a colour is not usable."""

    known = set(VisualTokens.model_fields)
    for name, value in overrides.items():
        if name not in known:
            raise MarksError(
                f"There is no colour called {name!r}. The ones you can set are: "
                f"{', '.join(sorted(known))}."
            )
        if name == "radius_px":
            if not str(value).isdigit() or not 0 <= int(value) <= 24:
                raise MarksError("radius_px is a whole number from 0 to 24, like 10.")
            continue
        if not _HEX.fullmatch(str(value)):
            raise MarksError(f"{name} needs a colour written like #E39A2D. You gave {value!r}.")


__all__ = [
    "MARKS_FILENAME",
    "MARKS_VERSION",
    "ConceptMarks",
    "MarkPin",
    "MarksError",
    "ReviewMarks",
    "check_token_overrides",
    "marks_from_choice",
    "parse_marks",
    "plain_reason",
    "read_marks",
]
