"""The taste verbs: `look`, `tokens`, and `vibe`.

These are the three ways a person tells the build what it should look like.
`look` makes a page you mark up in a browser and reads the marks back. `tokens`
changes colours, type, and spacing straight from the terminal. `vibe` reads a
palette off a picture or a page you already have.

Everything the page can do, a flag can do. Nobody has to open a browser to get
the same result, which matters for people using a screen reader and for agents
with no browser at all.

`cli.py` gets one line to attach these; no logic lives there.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import typer

from domain_foundry_core.foundry.models import (
    DENSITY_SCALE_LABELS,
    TYPOGRAPHY_STACK_LABELS,
    FoundrySpec,
)
from domain_foundry_core.review import (
    MARKS_FILENAME,
    BindingError,
    MarksError,
    VibeError,
    bind_look,
    check_token_overrides,
    marks_from_choice,
    proposal_from_spec,
    read_marks,
    read_reference,
    render_review_page,
)
from domain_foundry_core.review.page import TOPOLOGY_LABELS

PAGE_FILENAME = "review.html"
VIBE_FILENAME = "vibe-tokens.json"


def _fail(message: str) -> None:
    typer.echo(message, err=True)
    raise typer.Exit(code=2)


def _load(spec_path: Path) -> FoundrySpec:
    from domain_foundry_core.foundry import load_foundry_spec

    try:
        return load_foundry_spec(spec_path.resolve())
    except Exception as error:  # noqa: BLE001 - one plain sentence, never a traceback
        _fail(f"That spec could not be read: {error}")
        raise  # unreachable; keeps the type checker honest


def _review_dir(spec_path: Path, out: Path | None) -> Path:
    if out is not None:
        return out
    return spec_path.resolve().parent / f"{spec_path.stem}-review"


def _pairs(values: list[str]) -> dict[str, str]:
    overrides: dict[str, str] = {}
    for item in values:
        if "=" not in item:
            _fail(f"Write a colour as name=value, like accent=#E39A2D. You wrote {item!r}.")
        name, _, value = item.partition("=")
        overrides[name.strip()] = value.strip()
    return overrides


def _token_file(path: Path) -> dict[str, Any]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        _fail(f"There is no token file at {path}.")
        raise
    except json.JSONDecodeError as error:
        _fail(f"{path} is not valid JSON ({error.msg} on line {error.lineno}).")
        raise
    if not isinstance(raw, dict):
        _fail(f"{path} should hold one JSON object of settings.")
    payload = dict(raw)
    if "token_overrides" not in payload:
        known_keys = {"topology", "typography_stack", "density_scale", "signature_elements"}
        payload = {
            "token_overrides": {k: v for k, v in raw.items() if k not in known_keys},
            **{k: v for k, v in raw.items() if k in known_keys},
        }
    return payload


def _write_page(
    spec: FoundrySpec,
    directory: Path,
    *,
    previews: bool,
    proposed_tokens: dict[str, str] | None = None,
    proposed_from: str = "",
) -> Path:
    proposal = proposal_from_spec(
        spec,
        previews=previews,
        proposed_tokens=proposed_tokens,
        proposed_from=proposed_from,
    )
    directory.mkdir(parents=True, exist_ok=True)
    page = directory / PAGE_FILENAME
    page.write_text(render_review_page(proposal), encoding="utf-8")
    return page


# ---------------------------------------------------------------------------
# look
# ---------------------------------------------------------------------------


def look_cmd(
    spec_path: Path = typer.Argument(..., exists=True, dir_okay=False, readable=True),
    out: Path = typer.Option(None, "--out", help="Where the review page goes"),
    read: bool = typer.Option(False, "--read", help="Take in the marks you saved"),
    marks: Path = typer.Option(None, "--marks", help=f"A {MARKS_FILENAME} somewhere else"),
    choose: str = typer.Option(None, "--choose", help="Pick a concept without a browser"),
    tokens_file: Path = typer.Option(
        None, "--tokens", help="A JSON file of colours and settings to go with --choose"
    ),
    set_token: list[str] = typer.Option(
        [], "--set", help="One colour, written as accent=#E39A2D. Repeat for more."
    ),
    topology: str = typer.Option(None, "--topology", help=f"One of: {', '.join(TOPOLOGY_LABELS)}"),
    type_stack: str = typer.Option(
        None, "--type", help=f"One of: {', '.join(TYPOGRAPHY_STACK_LABELS)}"
    ),
    density: str = typer.Option(
        None, "--density", help=f"One of: {', '.join(DENSITY_SCALE_LABELS)}"
    ),
    note: list[str] = typer.Option([], "--note", help="Something to remember about this look"),
    previews: bool = typer.Option(
        True, "--previews/--no-previews", help="Put a working preview in each card"
    ),
    open_page: bool = typer.Option(
        False, "--open", help="Open the page in your browser as well as printing where it is"
    ),
) -> None:
    """Make a review page for a spec, or take in the marks you left on one.

    With no flags this writes a page you open from your own disk and mark up.
    `--read` takes the marks back in. `--choose` does the same job with no
    browser at all.
    """

    spec = _load(spec_path)
    directory = _review_dir(spec_path, out)

    if choose:
        overrides = _pairs(set_token)
        settings: dict[str, Any] = {}
        if tokens_file is not None:
            settings = _token_file(tokens_file)
            overrides = {**settings.get("token_overrides", {}), **overrides}
        try:
            check_token_overrides(overrides)
            binding = marks_from_choice(
                look_id=f"{spec.id}-look",
                concept_id=choose,
                token_overrides=overrides,
                topology=topology or settings.get("topology"),
                typography_stack=type_stack or settings.get("typography_stack"),
                density_scale=density or settings.get("density_scale"),
                signature_elements=settings.get("signature_elements"),
                notes=list(note),
            ).to_binding()
            bind_look(spec_path, binding)
        except (MarksError, BindingError) as error:
            _fail(str(error))
        typer.echo(
            json.dumps(
                {
                    "bound": True,
                    "spec": str(spec_path),
                    "concept": choose,
                    "from": "flags",
                    "next": f"Build it: domain-foundry foundry build {spec_path} -o ./app",
                }
            )
        )
        return

    if read:
        marks_path = marks if marks is not None else directory / MARKS_FILENAME
        try:
            saved = read_marks(marks_path)
            binding = saved.to_binding()
            bind_look(spec_path, binding)
        except (MarksError, BindingError) as error:
            _fail(str(error))
        typer.echo(
            json.dumps(
                {
                    "bound": True,
                    "spec": str(spec_path),
                    "concept": binding.concept_id,
                    "from": str(marks_path),
                    "colours_changed": sorted(binding.token_overrides),
                    "borrowed": [item.from_concept for item in binding.borrowed_fragments],
                    "notes": len(binding.notes),
                    "next": f"Build it: domain-foundry foundry build {spec_path} -o ./app",
                }
            )
        )
        return

    page = _write_page(spec, directory, previews=previews)
    if open_page:
        import webbrowser

        webbrowser.open(page.as_uri())
    bound = spec.look.concept_id if spec.look else None
    typer.echo(
        json.dumps(
            {
                "page": str(page),
                "concepts": [concept.id for concept in spec.concepts],
                "already_chosen": bound,
                "next": (
                    f"Open {page} in your browser, mark it up, press Save, then run: "
                    f"domain-foundry look {spec_path} --read"
                ),
            }
        )
    )


# ---------------------------------------------------------------------------
# tokens
# ---------------------------------------------------------------------------


def tokens_cmd(
    spec_path: Path = typer.Argument(..., exists=True, dir_okay=False, readable=True),
    set_token: list[str] = typer.Option(
        [], "--set", help="One colour, written as accent=#E39A2D. Repeat for more."
    ),
    from_file: Path = typer.Option(
        None, "--from", help=f"A settings file, such as the {VIBE_FILENAME} that vibe writes"
    ),
    type_stack: str = typer.Option(
        None, "--type", help=f"One of: {', '.join(TYPOGRAPHY_STACK_LABELS)}"
    ),
    density: str = typer.Option(
        None, "--density", help=f"One of: {', '.join(DENSITY_SCALE_LABELS)}"
    ),
    topology: str = typer.Option(None, "--topology", help=f"One of: {', '.join(TOPOLOGY_LABELS)}"),
    page: bool = typer.Option(False, "--page", help="Write a review page to change these by eye"),
    out: Path = typer.Option(None, "--out", help="Where that page goes"),
) -> None:
    """Show or change the colours, type, and spacing a build will use."""

    spec = _load(spec_path)
    overrides = _pairs(set_token)
    settings: dict[str, Any] = {}
    if from_file is not None:
        settings = _token_file(from_file)
        overrides = {**settings.get("token_overrides", {}), **overrides}
    type_stack = type_stack or settings.get("typography_stack")
    density = density or settings.get("density_scale")
    topology = topology or settings.get("topology")
    wants_change = bool(overrides or type_stack or density or topology)

    if page and not wants_change:
        directory = _review_dir(spec_path, out)
        written = _write_page(spec, directory, previews=True)
        typer.echo(
            json.dumps(
                {
                    "page": str(written),
                    "next": (
                        f"Open {written}, change what you want, press Save, then run: "
                        f"domain-foundry look {spec_path} --read"
                    ),
                }
            )
        )
        return

    if not wants_change:
        world = spec.experience.visual_world
        bound = spec.look
        colours = world.tokens.model_dump(mode="json")
        if bound is not None:
            colours.update(bound.token_overrides)
        stack = (bound.typography_stack if bound else None) or world.typography_stack
        scale = (bound.density_scale if bound else None) or world.density_scale
        shape = (bound.topology if bound else None) or spec.experience.navigation.topology
        typer.echo(
            json.dumps(
                {
                    "spec": spec.id,
                    "colours": colours,
                    "type": {
                        "name": stack or "not set yet",
                        "means": TYPOGRAPHY_STACK_LABELS.get(
                            stack or "", "the spec has not picked one yet"
                        ),
                    },
                    "room": {
                        "name": scale or "not set yet",
                        "means": DENSITY_SCALE_LABELS.get(
                            scale or "", "the spec has not picked one yet"
                        ),
                    },
                    "moving_around": {
                        "name": shape,
                        "means": TOPOLOGY_LABELS.get(shape, shape),
                    },
                    "next": (
                        "Change one: domain-foundry tokens "
                        f"{spec_path} --set accent=#E39A2D --density bench"
                    ),
                },
                indent=2,
            )
        )
        return

    bound = spec.look
    concept = (bound.concept_id if bound else None) or spec.remix.selected_concept
    merged = dict(bound.token_overrides) if bound else {}
    merged.update(overrides)
    try:
        check_token_overrides(merged)
        binding = marks_from_choice(
            look_id=(bound.look_id if bound else f"{spec.id}-look"),
            concept_id=concept,
            token_overrides=merged,
            topology=topology or (bound.topology if bound else None),
            typography_stack=type_stack or (bound.typography_stack if bound else None),
            density_scale=density or (bound.density_scale if bound else None),
            signature_elements=list(bound.signature_elements) if bound else None,
            notes=list(bound.notes) if bound else None,
        ).to_binding()
        if bound is not None:
            binding = binding.model_copy(update={"borrowed_fragments": bound.borrowed_fragments})
        bind_look(spec_path, binding)
    except (MarksError, BindingError) as error:
        _fail(str(error))
    written_page = None
    if page:
        written_page = str(
            _write_page(_load(spec_path), _review_dir(spec_path, out), previews=True)
        )
    typer.echo(
        json.dumps(
            {
                "changed": sorted(overrides),
                "type": binding.typography_stack,
                "room": binding.density_scale,
                "moving_around": binding.topology,
                "concept": binding.concept_id,
                "page": written_page,
                "next": f"Build it: domain-foundry foundry build {spec_path} -o ./app",
            }
        )
    )


# ---------------------------------------------------------------------------
# vibe
# ---------------------------------------------------------------------------


def vibe_cmd(
    reference: Path = typer.Argument(..., exists=True, dir_okay=False, readable=True),
    spec_path: Path = typer.Option(
        None, "--spec", help="A spec whose review page should show these colours"
    ),
    out: Path = typer.Option(None, "--out", help="Where the proposal and any page go"),
) -> None:
    """Read colours off a PNG picture, an HTML page, or a CSS file on your machine.

    Nothing is sent anywhere and nothing is saved to the spec. You get a
    proposal; you keep it by pressing Save on the review page or by running
    `tokens --from`.
    """

    try:
        reading = read_reference(reference)
    except VibeError as error:
        _fail(str(error))
        raise
    directory = out if out is not None else reference.resolve().parent
    if spec_path is not None and out is None:
        directory = _review_dir(spec_path, None)
    directory.mkdir(parents=True, exist_ok=True)
    proposal_path = directory / VIBE_FILENAME
    payload: dict[str, Any] = {"token_overrides": reading.tokens}
    if reading.typography_stack:
        payload["typography_stack"] = reading.typography_stack
    proposal_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    page_path = None
    if spec_path is not None:
        spec = _load(spec_path)
        page_path = str(
            _write_page(
                spec,
                directory,
                previews=True,
                proposed_tokens=reading.tokens,
                proposed_from=reading.source,
            )
        )
    next_step = (
        f"Keep these: domain-foundry tokens YOUR-SPEC.yaml --from {proposal_path}"
        if page_path is None
        else f"Open {page_path}, keep what you like, press Save, then run: "
        f"domain-foundry look {spec_path} --read"
    )
    typer.echo(
        json.dumps(
            {
                "read": reading.source,
                "kind": reading.kind,
                "colours": list(reading.colours),
                "proposed": reading.tokens,
                "type": reading.typography_stack,
                "saved_nothing_yet": True,
                "proposal": str(proposal_path),
                "page": page_path,
                "note": reading.note,
                "next": next_step,
            },
            indent=2,
        )
    )


def register(app: typer.Typer) -> None:
    """Attach the taste verbs to a Typer application."""

    app.command("look")(look_cmd)
    app.command("tokens")(tokens_cmd)
    app.command("vibe")(vibe_cmd)


__all__ = ["look_cmd", "register", "tokens_cmd", "vibe_cmd"]
