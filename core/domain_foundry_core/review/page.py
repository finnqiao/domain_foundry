"""The review page: three concepts, live previews, and controls you can mark up.

The page is one static HTML file. You open it from disk, mark it up, and press
Save. It never talks to a server, never asks for an account, and never sends
anything anywhere. Save hands you a `review-marks.json` file, which
`domain-foundry look --read` turns into the binding the build reads.

Every control on the page has a flag on the command line, so a person using a
screen reader, or an agent with no browser at all, can do the same work.
"""

from __future__ import annotations

import html
import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from domain_foundry_core.foundry.models import (
    DENSITY_SCALE_LABELS,
    SIGNATURE_ELEMENT_LABELS,
    TYPOGRAPHY_STACK_LABELS,
    FoundrySpec,
    LookBinding,
)

from .marks import MARKS_FILENAME, MARKS_VERSION

TOPOLOGY_LABELS: dict[str, str] = {
    "hub": "one home screen with everything branching off it",
    "workflow": "a set of steps you move through in order",
    "split": "a list on one side, the thing you picked on the other",
    "canvas": "one open surface you arrange things on",
    "session": "one thing at a time, until the sitting is done",
}

TOKEN_LABELS: dict[str, str] = {
    "background": "Page behind everything",
    "surface": "Cards and panels",
    "text": "Words",
    "muted": "Quieter words",
    "accent": "The one colour that stands out",
    "accent_alt": "A second stand-out colour",
    "border": "Lines and edges",
    "focus": "The ring around whatever you tabbed to",
    "danger": "Warnings and mistakes",
}

# The palette a wizard look starts from when there is no spec yet to read one
# off. Every value is editable on the page.
DEFAULT_PREVIEW_TOKENS: dict[str, str] = {
    "background": "#F7F7F1",
    "surface": "#FFFFFF",
    "text": "#17201D",
    "muted": "#5B6763",
    "accent": "#0D5F55",
    "accent_alt": "#B4531C",
    "border": "#CDD5D1",
    "focus": "#B4531C",
    "danger": "#A33A32",
    "radius_px": "10",
}

COLOUR_TOKENS: tuple[str, ...] = (
    "background",
    "surface",
    "text",
    "muted",
    "accent",
    "accent_alt",
    "border",
    "focus",
    "danger",
)

# Three starting points, so the three cards are actually worth comparing. The
# first is whatever the spec already says. The other two take the next two
# layouts in this fixed order, with matching spacing and type, so the same spec
# always produces the same three cards.
_TOPOLOGY_ORDER: tuple[str, ...] = ("hub", "workflow", "split", "canvas", "session")
_ALT_TYPE: tuple[str, ...] = ("data_sans", "rounded_humanist", "reading_serif", "mono_forward")
_ALT_DENSITY: tuple[str, ...] = ("dense", "airy", "bench")


@dataclass(frozen=True)
class ConceptCard:
    """One concept as the page shows it: a pitch, a look, and a live preview."""

    id: str
    title: str
    pitch: tuple[str, ...]
    feel: str
    best_at: str
    loop: str
    topology: str
    typography_stack: str
    density_scale: str
    tokens: dict[str, str]
    signature_elements: tuple[str, ...] = ()
    preview_html: str = ""
    preview_problem: str = ""
    pins: tuple[dict[str, Any], ...] = ()
    borrow: str = ""
    borrow_reason: str = ""
    notes: tuple[str, ...] = ()


@dataclass(frozen=True)
class ReviewProposal:
    """Everything one review page shows."""

    look_id: str
    title: str
    subject: str
    cards: tuple[ConceptCard, ...]
    chosen_concept: str | None = None
    notes: tuple[str, ...] = ()
    proposed_tokens: dict[str, str] = field(default_factory=dict)
    proposed_from: str = ""


def _plain(text: str) -> str:
    """Strip the punctuation the copy rules forbid, and tidy the spacing."""

    cleaned = str(text or "").replace("—", ", ").replace("–", ", ")
    cleaned = cleaned.replace(" ,", ",").replace(",,", ",")
    return " ".join(cleaned.split())


def _lower_first(text: str) -> str:
    text = _plain(text).rstrip(".")
    if not text:
        return text
    if len(text) > 1 and text[1].isupper():
        return text
    return text[0].lower() + text[1:]


def _artifact_sentence(artifacts: list[str]) -> str:
    picked = [_plain(item) for item in artifacts if _plain(item)][:3]
    if not picked:
        return "You already keep notes about this somewhere."
    if len(picked) == 1:
        return f"You already have {picked[0]}."
    return f"You already have {', '.join(picked[:-1])}, and {picked[-1]}."


def _pitch(spec: FoundrySpec, concept: Any) -> tuple[str, ...]:
    """Three sentences, the way a friend would say it."""

    want = _lower_first(spec.research.desired_outcome) or "keep track of this properly"
    build = _lower_first(concept.primary_affordance) or "a place to keep it all"
    return (
        f"Want to {want}?",
        _artifact_sentence(list(spec.research.existing_artifacts)),
        f"Build {build}.",
    )


def _feel(card_topology: str, typography_stack: str, density_scale: str, mood: str) -> str:
    mood_text = _plain(mood).rstrip(".")
    parts = [
        TOPOLOGY_LABELS.get(card_topology, card_topology),
        DENSITY_SCALE_LABELS.get(density_scale, density_scale),
        TYPOGRAPHY_STACK_LABELS.get(typography_stack, typography_stack),
    ]
    lead = f"{mood_text}: " if mood_text else ""
    return f"{lead}{parts[0]}, {parts[1]}, {parts[2]}."


def _variant_looks(spec: FoundrySpec) -> list[tuple[str, str, str]]:
    """Pick a topology, type stack, and density for each of the three cards."""

    own_topology = spec.experience.navigation.topology
    own_type = spec.experience.visual_world.typography_stack or "system_default"
    own_density = spec.experience.visual_world.density_scale or "bench"
    others = [name for name in _TOPOLOGY_ORDER if name != own_topology]
    picks = [(own_topology, own_type, own_density)]
    for index, topology in enumerate(others[:2]):
        picks.append((topology, _ALT_TYPE[index], _ALT_DENSITY[index]))
    return picks


def proposal_from_spec(
    spec: FoundrySpec,
    *,
    look_id: str | None = None,
    previews: bool = True,
    proposed_tokens: dict[str, str] | None = None,
    proposed_from: str = "",
) -> ReviewProposal:
    """Build the page's contents from a validated spec.

    A spec that already carries a binding starts from it: the bound concept is
    picked, its colours are filled in, and its notes are listed, so running
    `look` again continues where the last round left off.
    """

    bound = spec.look
    base_tokens = spec.experience.visual_world.tokens.model_dump(mode="json")
    base_tokens = {name: str(value) for name, value in base_tokens.items()}
    variants = _variant_looks(spec)
    cards: list[ConceptCard] = []
    for index, concept in enumerate(spec.concepts):
        topology, typography_stack, density_scale = variants[min(index, len(variants) - 1)]
        tokens = dict(base_tokens)
        if bound is not None and bound.concept_id == concept.id:
            topology = bound.topology or topology
            typography_stack = bound.typography_stack or typography_stack
            density_scale = bound.density_scale or density_scale
            tokens.update(bound.token_overrides)
        if proposed_tokens:
            tokens.update(proposed_tokens)
        signature = tuple(spec.experience.visual_world.signature_element_ids)
        if bound is not None and bound.concept_id == concept.id and bound.signature_elements:
            signature = tuple(bound.signature_elements)
        preview_html = ""
        preview_problem = ""
        if previews:
            preview_html, preview_problem = _compiled_preview(
                spec,
                concept_id=concept.id,
                topology=topology,
                typography_stack=typography_stack,
                density_scale=density_scale,
                tokens=tokens,
                signature=signature,
                look_id=look_id or f"{spec.id}-look",
            )
        cards.append(
            ConceptCard(
                id=concept.id,
                title=_plain(concept.title),
                pitch=_pitch(spec, concept),
                feel=_feel(
                    topology,
                    typography_stack,
                    density_scale,
                    spec.experience.visual_world.mood,
                ),
                best_at=_plain(concept.differentiator),
                loop=_plain(concept.primary_loop),
                topology=topology,
                typography_stack=typography_stack,
                density_scale=density_scale,
                tokens=tokens,
                signature_elements=signature,
                preview_html=preview_html,
                preview_problem=preview_problem,
                borrow=_borrowed_piece(bound, concept.id),
                borrow_reason=_borrowed_reason(bound, concept.id),
            )
        )
    return ReviewProposal(
        look_id=look_id or f"{spec.id}-look",
        title=_plain(spec.title),
        subject=_plain(spec.research.interest),
        cards=tuple(cards),
        chosen_concept=bound.concept_id if bound is not None else None,
        notes=tuple(bound.notes) if bound is not None else (),
        proposed_tokens=dict(proposed_tokens or {}),
        proposed_from=proposed_from,
    )


def _borrowed_piece(bound: LookBinding | None, concept_id: str) -> str:
    if bound is None:
        return ""
    for fragment in bound.borrowed_fragments:
        if fragment.from_concept == concept_id:
            return fragment.piece
    return ""


def _borrowed_reason(bound: LookBinding | None, concept_id: str) -> str:
    if bound is None:
        return ""
    for fragment in bound.borrowed_fragments:
        if fragment.from_concept == concept_id:
            return fragment.reason or ""
    return ""


def _compiled_preview(
    spec: FoundrySpec,
    *,
    concept_id: str,
    topology: str,
    typography_stack: str,
    density_scale: str,
    tokens: dict[str, str],
    signature: tuple[str, ...],
    look_id: str,
) -> tuple[str, str]:
    """Compile the real app for this card, so the preview is the thing itself.

    Returns the page and an empty string, or an empty page and a plain sentence
    saying why there is no preview. A missing preview never stops the review.
    """

    from domain_foundry_core.foundry.compiler import FoundryCompiler

    data = spec.model_dump(mode="json")
    world = data["experience"]["visual_world"]
    world_tokens = dict(world["tokens"])
    for name, value in tokens.items():
        if name == "radius_px":
            world_tokens[name] = int(value)
        elif name in world_tokens:
            world_tokens[name] = value
    world["tokens"] = world_tokens
    world["typography_stack"] = typography_stack
    world["density_scale"] = density_scale
    if signature:
        world["signature_element_ids"] = list(signature)
    data["experience"]["navigation"]["topology"] = topology
    data["remix"]["selected_concept"] = concept_id
    data["look"] = {
        "look_id": look_id,
        "concept_id": concept_id,
        "topology": topology,
        "typography_stack": typography_stack,
        "density_scale": density_scale,
        "token_overrides": {
            name: str(value) for name, value in tokens.items() if name != "radius_px"
        },
        "signature_elements": list(signature),
    }
    try:
        variant = FoundrySpec.model_validate(data)
        return FoundryCompiler().render_app(variant), ""
    except Exception as error:  # noqa: BLE001 - a broken preview must not block review
        return "", f"No preview for this one: {type(error).__name__}: {error}"


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def _e(value: Any) -> str:
    return html.escape(str(value), quote=True)


def _select(
    *, concept: str, field_name: str, label: str, options: dict[str, str], current: str
) -> str:
    option_html = "".join(
        f'<option value="{_e(key)}"{" selected" if key == current else ""}>'
        f"{_e(key.replace('_', ' '))}: {_e(text)}</option>"
        for key, text in options.items()
    )
    control_id = f"{concept}-{field_name}"
    return (
        f'<p class="field"><label for="{_e(control_id)}">{_e(label)}</label>'
        f'<select id="{_e(control_id)}" data-field="{_e(field_name)}">{option_html}</select></p>'
    )


def _colour_fields(card: ConceptCard) -> str:
    rows = []
    for name in COLOUR_TOKENS:
        value = card.tokens.get(name, "#000000")
        control_id = f"{card.id}-{name}"
        rows.append(
            f'<p class="field colour">'
            f'<label for="{_e(control_id)}">{_e(TOKEN_LABELS[name])} ({_e(name)})</label>'
            f'<span class="swatch" data-swatch="{_e(name)}" '
            f'style="background:{_e(value)}" aria-hidden="true"></span>'
            f'<input id="{_e(control_id)}" type="text" spellcheck="false" '
            f'data-token="{_e(name)}" value="{_e(value)}" '
            f'aria-describedby="{_e(card.id)}-hex-help">'
            f'<input type="color" data-picker="{_e(name)}" value="{_e(value)}" '
            f'aria-label="Pick {_e(name)} from a colour wheel">'
            f"</p>"
        )
    radius = card.tokens.get("radius_px", "10")
    radius_id = f"{card.id}-radius_px"
    rows.append(
        f'<p class="field"><label for="{_e(radius_id)}">Corner rounding in pixels '
        f"(radius_px)</label>"
        f'<input id="{_e(radius_id)}" type="number" min="0" max="24" step="1" '
        f'data-token="radius_px" value="{_e(radius)}"></p>'
    )
    return "".join(rows)


def _signature_fields(card: ConceptCard) -> str:
    boxes = []
    for name, text in SIGNATURE_ELEMENT_LABELS.items():
        control_id = f"{card.id}-sig-{name}"
        checked = " checked" if name in card.signature_elements else ""
        boxes.append(
            f'<p class="field check"><input id="{_e(control_id)}" type="checkbox" '
            f'data-signature="{_e(name)}"{checked}>'
            f'<label for="{_e(control_id)}">{_e(text)}</label></p>'
        )
    return "".join(boxes)


def _preview_block(card: ConceptCard) -> str:
    if card.preview_html:
        srcdoc = _e(card.preview_html)
        frame = (
            f'<iframe class="preview" title="Working preview of {_e(card.title)}" '
            f'sandbox="allow-scripts" loading="lazy" srcdoc="{srcdoc}"></iframe>'
        )
    else:
        problem = card.preview_problem or "No preview was built for this one."
        frame = f'<p class="preview-missing">{_e(problem)}</p>'
    return (
        f'<div class="preview-wrap">{frame}'
        f'<button type="button" class="pin-layer" data-pin-layer '
        f'aria-label="Pin a note on {_e(card.title)}. Turn pinning on first." '
        f"hidden></button></div>"
    )


def _card_html(card: ConceptCard, chosen: str | None) -> str:
    picked = " checked" if chosen == card.id else ""
    chosen_badge = (
        '<span class="badge" data-chosen-badge>Chosen</span>'
        if chosen == card.id
        else '<span class="badge" data-chosen-badge hidden>Chosen</span>'
    )
    pitch = "".join(f"<p>{_e(line)}</p>" for line in card.pitch)
    return f"""
<section class="card" data-concept="{_e(card.id)}" aria-labelledby="{_e(card.id)}-title">
  <h2 id="{_e(card.id)}-title">{_e(card.title)} {chosen_badge}</h2>
  <div class="pitch">{pitch}</div>
  <p class="feel">Design and feel: {_e(card.feel)}</p>
  <p class="field radio">
    <input type="radio" name="chosen" id="{_e(card.id)}-chosen" value="{_e(card.id)}"{picked}>
    <label for="{_e(card.id)}-chosen">Build this one</label>
  </p>
  {_preview_block(card)}
  <p class="field toggle">
    <button type="button" data-pin-toggle aria-pressed="false">Pin notes on this preview</button>
    <button type="button" data-pin-add>Add a note without clicking</button>
  </p>
  <h3 id="{_e(card.id)}-pins-title">Notes pinned on this one</h3>
  <ul class="pins" data-pin-list aria-labelledby="{_e(card.id)}-pins-title"></ul>
  <details>
    <summary>Change the look of this one</summary>
    {
        _select(
            concept=card.id,
            field_name="topology",
            label="How you move around it",
            options=TOPOLOGY_LABELS,
            current=card.topology,
        )
    }
    {
        _select(
            concept=card.id,
            field_name="typography_stack",
            label="Type",
            options=TYPOGRAPHY_STACK_LABELS,
            current=card.typography_stack,
        )
    }
    {
        _select(
            concept=card.id,
            field_name="density_scale",
            label="How much room things get",
            options=DENSITY_SCALE_LABELS,
            current=card.density_scale,
        )
    }
    <h4>Pieces to show</h4>
    {_signature_fields(card)}
    <h4>Colours</h4>
    <p id="{
        _e(card.id)
    }-hex-help" class="help">Write a colour as six characters after a hash, like #E39A2D.</p>
    {_colour_fields(card)}
  </details>
  <details>
    <summary>What this one is good at</summary>
    <p>{_e(card.best_at)}</p>
    <p>What you do in it: {_e(card.loop)}</p>
  </details>
  <p class="field">
    <label for="{_e(card.id)}-borrow">A piece of this one to keep, even if you build
    another</label>
    <input id="{_e(card.id)}-borrow" type="text" data-borrow value="{_e(card.borrow)}"
      placeholder="the big Feed now button">
  </p>
  <p class="field">
    <label for="{_e(card.id)}-borrow-reason">Why you want that piece</label>
    <input id="{_e(card.id)}-borrow-reason" type="text" data-borrow-reason
      value="{_e(card.borrow_reason)}">
  </p>
</section>
"""


def render_review_page(proposal: ReviewProposal) -> str:
    """Return the whole review page as one self contained HTML file."""

    cards = "".join(_card_html(card, proposal.chosen_concept) for card in proposal.cards)
    state = {
        "marks_version": MARKS_VERSION,
        "look_id": proposal.look_id,
        "filename": MARKS_FILENAME,
        "pins": {card.id: [dict(pin) for pin in card.pins] for card in proposal.cards},
    }
    proposed = ""
    if proposal.proposed_tokens:
        source = proposal.proposed_from or "a reference you pointed at"
        names = ", ".join(sorted(proposal.proposed_tokens))
        proposed = (
            f'<p class="notice">These colours came from {_e(source)} and are filled in '
            f"below, but nothing is saved yet: {_e(names)}. Keep them by pressing Save, "
            f"or type over them first.</p>"
        )
    notes = "\n".join(proposal.notes)
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Review the look for {_e(proposal.title)}</title>
<style>
{_CSS}
</style>
</head>
<body>
<a class="skip" href="#concepts">Skip to the concepts</a>
<header>
  <h1>Review the look for {_e(proposal.title)}</h1>
  <p class="lede">{_e(proposal.subject)}</p>
  <p>Three ways to build it, each one running below its pitch. Pick one, change
  its colours, type, and spacing, pin notes where something is wrong, then press
  Save at the bottom.</p>
  <p>This page is a file on your machine. It sends nothing anywhere. The
  previews do not keep anything you type into them.</p>
  {proposed}
</header>
<main id="concepts">
{cards}
<section class="card">
  <h2>Anything else</h2>
  <p class="field">
    <label for="extra-notes">Notes about the whole thing, one per line</label>
    <textarea id="extra-notes" rows="4">{_e(notes)}</textarea>
  </p>
</section>
<section class="card" id="save-marks">
  <h2>Save your marks</h2>
  <p>Save hands you a file called {_e(MARKS_FILENAME)}. Put it next to this page,
  then run this in a terminal:</p>
  <pre><code>domain-foundry look YOUR-SPEC.yaml --read</code></pre>
  <p>If your browser puts it somewhere else, point at it:
  <code>--marks ~/Downloads/{_e(MARKS_FILENAME)}</code></p>
  <p class="field toggle">
    <button type="button" id="save">Save my marks</button>
    <button type="button" id="copy">Copy my marks instead</button>
  </p>
  <p class="status" id="status" role="status" aria-live="polite"></p>
  <p class="field">
    <label for="marks-text">Your marks as text, if you would rather copy them by
    hand</label>
    <textarea id="marks-text" rows="6" readonly></textarea>
  </p>
</section>
</main>
<script>
window.__REVIEW__ = {json.dumps(state, ensure_ascii=False)};
{_JS}
</script>
</body>
</html>
"""


_CSS = """
:root {
  color-scheme: light dark;
  --bg: #f7f7f1; --surface: #ffffff; --ink: #17201d; --muted: #5b6763;
  --line: #cdd5d1; --accent: #0d5f55; --focus: #b4531c;
}
@media (prefers-color-scheme: dark) {
  :root { --bg: #101613; --surface: #17201d; --ink: #e8eeeb; --muted: #9fada8;
    --line: #2b3733; --accent: #58c7ad; --focus: #f0a35c; }
}
* { box-sizing: border-box; }
body { margin: 0; background: var(--bg); color: var(--ink); padding: 16px;
  font: 16px/1.5 ui-sans-serif, system-ui, -apple-system, sans-serif; }
header, main { max-width: 62rem; margin: 0 auto; }
h1 { font-size: 1.5rem; margin: 0 0 8px; }
h2 { font-size: 1.2rem; margin: 0 0 8px; }
h3, h4 { font-size: 1rem; margin: 16px 0 4px; }
.lede { color: var(--muted); margin: 0 0 12px; }
.card { background: var(--surface); border: 1px solid var(--line); border-radius: 12px;
  padding: 16px; margin: 16px 0; }
.card[data-picked="yes"] { border-color: var(--accent); border-width: 3px; }
.badge { font-size: .75rem; border: 1px solid var(--accent); border-radius: 999px;
  padding: 2px 8px; vertical-align: middle; }
.pitch p { margin: 0 0 4px; }
.feel { color: var(--muted); margin: 8px 0 12px; }
.field { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; margin: 8px 0; }
.field label { flex: 1 1 14rem; }
.field.check, .field.radio { align-items: baseline; }
.field.check label, .field.radio label { flex: 1 1 auto; }
.field.toggle { gap: 12px; }
input[type="text"], input[type="number"], select, textarea {
  font: inherit; color: inherit; background: var(--bg); border: 1px solid var(--line);
  border-radius: 8px; padding: 6px 8px; min-width: 0; flex: 1 1 10rem; max-width: 100%; }
textarea { width: 100%; flex-basis: 100%; }
button { font: inherit; color: inherit; background: var(--surface);
  border: 1px solid var(--line); border-radius: 8px; padding: 8px 12px; cursor: pointer; }
button[aria-pressed="true"] { border-width: 3px; border-color: var(--accent); }
button[aria-pressed="true"]::after { content: " (on)"; }
:focus-visible { outline: 3px solid var(--focus); outline-offset: 2px; }
.swatch { width: 1.6rem; height: 1.6rem; border-radius: 6px; border: 1px solid var(--line);
  display: inline-block; }
.preview-wrap { position: relative; margin: 12px 0; }
.preview { width: 100%; height: 22rem; border: 1px solid var(--line); border-radius: 10px;
  background: var(--bg); }
.preview-missing { border: 1px dashed var(--line); border-radius: 10px; padding: 12px;
  color: var(--muted); }
.pin-layer { position: absolute; inset: 0; width: 100%; height: 100%; background: transparent;
  border: 3px dashed var(--accent); border-radius: 10px; }
.pins { list-style: none; padding: 0; margin: 0; }
.pins li { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; margin: 6px 0; }
.pins .where { color: var(--muted); font-size: .85rem; flex: 0 0 auto; }
.help, .status { color: var(--muted); }
.notice { border: 1px solid var(--accent); border-radius: 8px; padding: 10px; }
.skip { position: absolute; left: -9999px; }
.skip:focus { position: static; display: inline-block; margin-bottom: 8px; }
pre { overflow-x: auto; background: var(--bg); border: 1px solid var(--line);
  border-radius: 8px; padding: 8px; }
@media (max-width: 30rem) {
  body { padding: 10px; }
  .field label { flex-basis: 100%; }
  .preview { height: 16rem; }
}
"""


_JS = """
(function () {
  var state = window.__REVIEW__;
  var pins = state.pins || {};

  function where(x, y) {
    var across = x < 34 ? "left" : (x < 67 ? "middle" : "right");
    var down = y < 34 ? "top" : (y < 67 ? "middle" : "bottom");
    if (across === "middle" && down === "middle") return "in the middle";
    if (across === "middle") return down + " of the page";
    if (down === "middle") return "the " + across + " side";
    return down + " " + across;
  }

  function renderPins(card) {
    var id = card.getAttribute("data-concept");
    var list = card.querySelector("[data-pin-list]");
    list.textContent = "";
    (pins[id] || []).forEach(function (pin, index) {
      var item = document.createElement("li");
      var spot = document.createElement("span");
      spot.className = "where";
      spot.textContent = where(pin.x, pin.y) + ":";
      var input = document.createElement("input");
      input.type = "text";
      input.value = pin.text || "";
      input.setAttribute("aria-label", "Note pinned at " + where(pin.x, pin.y));
      input.addEventListener("input", function () { pin.text = input.value; });
      var drop = document.createElement("button");
      drop.type = "button";
      drop.textContent = "Remove";
      drop.addEventListener("click", function () {
        pins[id].splice(index, 1);
        renderPins(card);
      });
      item.appendChild(spot);
      item.appendChild(input);
      item.appendChild(drop);
      list.appendChild(item);
    });
    if (!(pins[id] || []).length) {
      var empty = document.createElement("li");
      empty.textContent = "Nothing pinned on this one yet.";
      list.appendChild(empty);
    }
  }

  function addPin(card, x, y) {
    var id = card.getAttribute("data-concept");
    if (!pins[id]) pins[id] = [];
    pins[id].push({ x: x, y: y, text: "" });
    renderPins(card);
    var inputs = card.querySelectorAll("[data-pin-list] input");
    if (inputs.length) inputs[inputs.length - 1].focus();
  }

  function markPicked() {
    document.querySelectorAll(".card[data-concept]").forEach(function (card) {
      var radio = card.querySelector("input[name=chosen]");
      var on = !!(radio && radio.checked);
      card.setAttribute("data-picked", on ? "yes" : "no");
      var badge = card.querySelector("[data-chosen-badge]");
      if (badge) badge.hidden = !on;
    });
  }

  document.querySelectorAll(".card[data-concept]").forEach(function (card) {
    renderPins(card);
    var layer = card.querySelector("[data-pin-layer]");
    var toggle = card.querySelector("[data-pin-toggle]");
    if (toggle && layer) {
      toggle.addEventListener("click", function () {
        var on = toggle.getAttribute("aria-pressed") === "true";
        toggle.setAttribute("aria-pressed", on ? "false" : "true");
        layer.hidden = on;
      });
      layer.addEventListener("click", function (event) {
        var box = layer.getBoundingClientRect();
        var x = box.width ? ((event.clientX - box.left) / box.width) * 100 : 50;
        var y = box.height ? ((event.clientY - box.top) / box.height) * 100 : 50;
        addPin(card, Math.min(100, Math.max(0, x)), Math.min(100, Math.max(0, y)));
      });
    }
    var add = card.querySelector("[data-pin-add]");
    if (add) add.addEventListener("click", function () { addPin(card, 50, 50); });
    card.querySelectorAll("[data-token]").forEach(function (input) {
      var name = input.getAttribute("data-token");
      var swatch = card.querySelector('[data-swatch="' + name + '"]');
      var picker = card.querySelector('[data-picker="' + name + '"]');
      input.addEventListener("input", function () {
        if (swatch) swatch.style.background = input.value;
        if (picker && /^#[0-9A-Fa-f]{6}$/.test(input.value)) picker.value = input.value;
      });
      if (picker) picker.addEventListener("input", function () {
        input.value = picker.value.toUpperCase();
        if (swatch) swatch.style.background = input.value;
      });
    });
    var radio = card.querySelector("input[name=chosen]");
    if (radio) radio.addEventListener("change", markPicked);
  });
  markPicked();

  function collect() {
    var concepts = {};
    document.querySelectorAll(".card[data-concept]").forEach(function (card) {
      var id = card.getAttribute("data-concept");
      var tokens = {};
      card.querySelectorAll("[data-token]").forEach(function (input) {
        tokens[input.getAttribute("data-token")] = input.value.trim();
      });
      var signature = [];
      card.querySelectorAll("[data-signature]").forEach(function (box) {
        if (box.checked) signature.push(box.getAttribute("data-signature"));
      });
      var notes = [];
      var borrow = card.querySelector("[data-borrow]");
      var reason = card.querySelector("[data-borrow-reason]");
      concepts[id] = {
        topology: card.querySelector('[data-field="topology"]').value,
        typography_stack: card.querySelector('[data-field="typography_stack"]').value,
        density_scale: card.querySelector('[data-field="density_scale"]').value,
        token_overrides: tokens,
        signature_elements: signature,
        pins: (pins[id] || []).filter(function (pin) {
          return (pin.text || "").trim().length > 0;
        }),
        borrow: borrow && borrow.value.trim() ? borrow.value.trim() : null,
        borrow_reason: reason && reason.value.trim() ? reason.value.trim() : null,
        notes: notes
      };
    });
    var picked = document.querySelector("input[name=chosen]:checked");
    var extra = document.getElementById("extra-notes").value.split("\\n")
      .map(function (line) { return line.trim(); })
      .filter(function (line) { return line.length > 0; });
    return {
      marks_version: state.marks_version,
      look_id: state.look_id,
      chosen_concept: picked ? picked.value : null,
      concepts: concepts,
      notes: extra,
      saved_at: new Date().toISOString().replace(/\\.\\d+Z$/, "Z")
    };
  }

  function say(message) {
    document.getElementById("status").textContent = message;
  }

  document.getElementById("save").addEventListener("click", function () {
    var text = JSON.stringify(collect(), null, 2);
    document.getElementById("marks-text").value = text;
    var blob = new Blob([text], { type: "application/json" });
    var link = document.createElement("a");
    link.href = URL.createObjectURL(blob);
    link.download = state.filename;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    setTimeout(function () { URL.revokeObjectURL(link.href); }, 1000);
    say("Saved " + state.filename + ". Move it next to this page and run the command above.");
  });

  document.getElementById("copy").addEventListener("click", function () {
    var text = JSON.stringify(collect(), null, 2);
    var box = document.getElementById("marks-text");
    box.value = text;
    box.focus();
    box.select();
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(text).then(function () {
        say("Your marks are on the clipboard.");
      }, function () {
        say("Your marks are in the box below. Copy them from there.");
      });
    } else {
      say("Your marks are in the box below. Copy them from there.");
    }
  });
})();
"""


def proposal_from_look(
    look: Mapping[str, Any], *, tokens: dict[str, str] | None = None
) -> ReviewProposal:
    """Build a review page around one look the wizard generated.

    The wizard used to write these looks to disk and never read them again.
    Now the look becomes the preview inside a page a person can mark up, which
    is the same page and the same marks file `look --read` takes back in.
    """

    from domain_foundry_core.wizard.fork import JOB_PITCH

    hero = str(look.get("hero_job") or "event_log")
    title = _plain(look.get("title") or "Look")
    idea_id = str(look.get("idea_id") or "look")
    palette = dict(tokens or DEFAULT_PREVIEW_TOKENS)
    card = ConceptCard(
        id=idea_id,
        title=title,
        pitch=(
            f"Want a {_lower_first(title)}?",
            _plain(look.get("pitch") or "This is the shape it would take."),
            f"Build {JOB_PITCH.get(hero, hero)}.",
        ),
        feel=_feel("hub", "system_default", "bench", ""),
        best_at=_plain(look.get("pitch") or ""),
        loop=f"What it is built around: {JOB_PITCH.get(hero, hero)}.",
        topology="hub",
        typography_stack="system_default",
        density_scale="bench",
        tokens=palette,
        preview_html=str(look.get("html") or ""),
        preview_problem="" if look.get("html") else "This look has no page to show yet.",
    )
    return ReviewProposal(
        look_id=f"{idea_id}-round-{int(look.get('round') or 1)}",
        title=title,
        subject=_plain(look.get("pitch") or ""),
        cards=(card,),
    )


__all__ = [
    "COLOUR_TOKENS",
    "DEFAULT_PREVIEW_TOKENS",
    "TOKEN_LABELS",
    "TOPOLOGY_LABELS",
    "ConceptCard",
    "ReviewProposal",
    "proposal_from_look",
    "proposal_from_spec",
    "render_review_page",
]
