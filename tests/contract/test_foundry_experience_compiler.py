"""Lane B contract: the spec's experience fields reach the compiled app.

Every test here asks one question: does something a person wrote in the spec
change what the app looks like or how it behaves? A field nobody reads is a
release blocker, so each phase of Lane B leaves its proof in this file.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from domain_foundry_core.foundry import compiler as module
from domain_foundry_core.foundry.compiler import FoundryCompiler, sanitize_bespoke_css
from domain_foundry_core.foundry.loader import load_golden_specs
from domain_foundry_core.foundry.models import (
    BespokeLayer,
    LookBinding,
)

RUNTIME = Path(module.__file__).with_name("runtime.js").read_text(encoding="utf-8")
SOURCE = Path(module.__file__).read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def goldens():
    return load_golden_specs()


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _by_id(goldens, spec_id):
    return next(spec for spec in goldens if spec.id == spec_id)


# --------------------------------------------------------------------------
# B1: the stylesheet is composed from parts, and the build stays deterministic.
# --------------------------------------------------------------------------


def test_the_same_spec_always_compiles_to_the_same_bytes(goldens) -> None:
    compiler = FoundryCompiler()
    for spec in goldens:
        assert _digest(compiler.render_app(spec)) == _digest(compiler.render_app(spec))


def test_the_stylesheet_is_assembled_from_named_parts(goldens) -> None:
    sheet = FoundryCompiler().render_stylesheet(goldens[0])
    assert module._RESET_CSS in sheet
    assert module._BASE_SHELL_CSS in sheet
    assert module._RESPONSIVE_CSS in sheet
    assert module._MOTION_CSS in sheet
    assert sheet in FoundryCompiler().render_app(goldens[0])


# --------------------------------------------------------------------------
# B2: five topologies, five layouts.
# --------------------------------------------------------------------------


def test_every_topology_has_its_own_layout_and_its_own_structure() -> None:
    names = ["hub", "workflow", "split", "canvas", "session"]
    assert set(module._TOPOLOGY_CSS) == set(names)
    assert set(module._TOPOLOGY_NARROW_CSS) == set(names)
    blocks = [module._TOPOLOGY_CSS[name] for name in names]
    assert len(set(blocks)) == len(names)
    for name in names:
        assert f'body[data-topology="{name}"]' in module._TOPOLOGY_CSS[name]
    # The app's own script builds a different arrangement for each one.
    for marker in (
        "hub-overview",
        "workflow-track",
        "split-detail",
        "canvas-board",
        "session-stage",
    ):
        assert marker in RUNTIME


def test_a_build_carries_only_the_layout_it_uses(goldens) -> None:
    compiler = FoundryCompiler()
    for spec in goldens:
        plan = compiler.experience_plan(spec)
        sheet = compiler.render_stylesheet(spec, plan)
        assert module._TOPOLOGY_CSS[plan.topology] in sheet
        for name, block in module._TOPOLOGY_CSS.items():
            if name != plan.topology:
                assert block not in sheet


def test_the_body_says_which_layout_type_and_density_this_app_uses(goldens) -> None:
    compiler = FoundryCompiler()
    for spec in goldens:
        plan = compiler.experience_plan(spec)
        html = compiler.render_app(spec)
        assert f'data-topology="{plan.topology}"' in html
        assert f'data-density="{plan.density_scale}"' in html
        assert f'data-type-stack="{plan.typography_stack}"' in html
        assert f'data-world="{spec.experience.visual_world.id}"' in html


# --------------------------------------------------------------------------
# B3: type, density and signature elements.
# --------------------------------------------------------------------------


def test_the_three_goldens_do_not_share_a_look(goldens) -> None:
    plans = [FoundryCompiler().experience_plan(spec) for spec in goldens]
    assert len({plan.topology for plan in plans}) == 3
    assert len({plan.typography_stack for plan in plans}) == 3
    assert len({plan.density_scale for plan in plans}) == 3
    assert len({plan.signature_elements for plan in plans}) == 3


def test_prose_about_type_and_room_is_mapped_and_the_receipt_says_so(goldens) -> None:
    plan = FoundryCompiler().experience_plan(_by_id(goldens, "card-collector"))
    receipt = plan.for_receipt()
    assert receipt["typography_stack"] == "data_sans"
    assert receipt["typography_stack_from"] == "mapped from the spec's description"
    assert receipt["density_scale"] == "dense"
    assert receipt["density_scale_from"] == "mapped from the spec's description"


def test_a_named_stack_beats_the_prose(goldens) -> None:
    spec = _by_id(goldens, "card-collector")
    world = spec.experience.visual_world.model_copy(
        update={
            "typography_stack": "mono_forward",
            "density_scale": "airy",
            "signature_element_ids": ["life_list"],
        }
    )
    experience = spec.experience.model_copy(update={"visual_world": world})
    plan = FoundryCompiler().experience_plan(spec.model_copy(update={"experience": experience}))
    assert plan.typography_stack == "mono_forward"
    assert plan.density_scale == "airy"
    assert plan.signature_elements == ("life_list",)
    assert plan.for_receipt()["typography_stack_from"] == "named in the spec"


def test_the_chosen_type_stack_and_density_are_written_into_the_stylesheet(goldens) -> None:
    compiler = FoundryCompiler()
    for spec in goldens:
        plan = compiler.experience_plan(spec)
        sheet = compiler.render_stylesheet(spec, plan)
        assert module._TYPOGRAPHY_STACKS[plan.typography_stack] in sheet
        assert module._DENSITY_CSS[plan.density_scale] in sheet
        assert "font-family: var(--font-body);" in sheet


def test_every_signature_element_has_a_renderer_and_only_asked_for_ones_ship(goldens) -> None:
    assert set(module._SIGNATURE_CSS) == {
        "progress_bar",
        "life_list",
        "comparison_strip",
        "timeline_rail",
        "gap_grid",
    }
    for name in module._SIGNATURE_CSS:
        assert f"{name}:" in RUNTIME  # the renderer is wired to the name
    compiler = FoundryCompiler()
    for spec in goldens:
        plan = compiler.experience_plan(spec)
        sheet = compiler.render_stylesheet(spec, plan)
        for name, block in module._SIGNATURE_CSS.items():
            assert (block in sheet) is (name in plan.signature_elements)


def test_every_visual_world_field_has_a_reader(goldens) -> None:
    world = goldens[0].experience.visual_world
    readers = SOURCE + RUNTIME
    for field in world.__class__.model_fields:
        assert field in readers, f"visual_world.{field} is read by nothing"


def test_every_experience_field_has_a_reader(goldens) -> None:
    experience = goldens[0].experience
    readers = SOURCE + RUNTIME
    for field in experience.__class__.model_fields:
        if field == "mode":
            continue  # one fixed value; there is nothing to render
        assert field in readers, f"experience.{field} is read by nothing"


# --------------------------------------------------------------------------
# B4: the small-screen sentences and the keyboard sentences drive behaviour.
# --------------------------------------------------------------------------


def test_the_small_screen_sentence_sets_the_order_regions_collapse_in(goldens) -> None:
    spec = _by_id(goldens, "sourdough-lab")
    plan = FoundryCompiler().experience_plan(spec)
    bench = {
        key.split(":", 1)[1]: value
        for key, value in plan.collapse.items()
        if key.startswith("bench:")
    }
    # "On phones the live decision and Feed now action precede the curve"
    assert bench["live_curve"]["order"] < bench["feeding_rail"]["order"]
    # "comparison becomes horizontally paged"
    assert plan.collapse["experiment_compare:comparison_table"]["paged"] is True
    assert "--collapse-order" in RUNTIME
    assert 'data-narrow="paged"' in RUNTIME


def test_the_keyboard_sentences_turn_into_keys_the_app_handles(goldens) -> None:
    compiler = FoundryCompiler()
    japanese = compiler.experience_plan(_by_id(goldens, "japanese-study-coach")).keyboard
    assert japanese["space_reveals"] is True
    assert japanese["escape_returns_to_main"] is True
    assert japanese["focus_after_capture"] == "status"

    cards = compiler.experience_plan(_by_id(goldens, "card-collector")).keyboard
    assert cards["arrow_navigation"] is True

    sourdough = compiler.experience_plan(_by_id(goldens, "sourdough-lab")).keyboard
    assert sourdough["arrow_navigation"] is False
    assert sourdough["focus_after_capture"] == "record"

    for marker in ("installKeyboard", "arrow_navigation", "space_reveals", "focusAfterCapture"):
        assert marker in RUNTIME


# --------------------------------------------------------------------------
# B5: the bespoke layer, inside its envelope.
# --------------------------------------------------------------------------

GOOD_LAYER = """
.region { border-radius: var(--radius); padding: 1rem; }
.region h3 { letter-spacing: .08em; text-transform: uppercase; color: var(--muted); }
.regions { grid-template-columns: repeat(4, minmax(0, 1fr)); }
"""

HOSTILE_LAYERS = {
    "a network request": ".region { background: url(https://example.com/pixel.png); }",
    "an import": "@import 'https://example.com/theme.css'; .region { color: var(--ink); }",
    "a script tag": ".region { color: var(--ink); } </style><script>alert(1)</script>",
    "an escape": ".region { color: var(--ink); \\7d  }",
    "a raw colour": ".region { color: #ff0000; }",
    "a colour function": ".region { background: rgb(255, 0, 0); }",
    "a property outside the list": ".region { content: 'x'; }",
    "a position fix": ".region { z-index: 99999; }",
    "an id selector": "#capture-dialog { display: none; }",
    "a universal selector": "* { display: none; }",
    "an unknown token": ".region { color: var(--secret); }",
    "a font size outside the scale": ".region { font-size: 40rem; }",
    "text outside a rule": "body { } drop table users;",
    "an oversized payload": ".region { color: var(--ink); }" + (" " * 9000),
}


def test_a_layer_inside_the_envelope_is_kept_and_scoped() -> None:
    css, problems = sanitize_bespoke_css(GOOD_LAYER)
    assert problems == []
    assert css is not None
    assert ".app .region {" in css
    assert ".app .regions {" in css
    assert "url(" not in css


@pytest.mark.parametrize("label", sorted(HOSTILE_LAYERS))
def test_a_layer_outside_the_envelope_is_dropped_whole(label) -> None:
    css, problems = sanitize_bespoke_css(HOSTILE_LAYERS[label])
    assert css is None
    assert problems, f"{label} was accepted"


def test_a_good_layer_reaches_the_page_and_the_receipt(goldens, tmp_path) -> None:
    spec = _by_id(goldens, "sourdough-lab")
    world = spec.experience.visual_world.model_copy(
        update={
            "bespoke": BespokeLayer(css=GOOD_LAYER, rationale="Give the bench wider region cards.")
        }
    )
    experience = spec.experience.model_copy(update={"visual_world": world})
    with_layer = spec.model_copy(update={"experience": experience})

    artifact = FoundryCompiler().compile(with_layer, tmp_path / "bespoke")
    html = artifact.app.read_text(encoding="utf-8")
    assert ".app .region {" in html
    receipt = json.loads(artifact.receipt.read_text(encoding="utf-8"))
    assert receipt["experience"]["bespoke_layer"] == "rendered"
    assert receipt["experience"]["bespoke_rejections"] == []


def test_a_rejected_layer_still_builds_and_the_receipt_says_why(goldens, tmp_path) -> None:
    spec = _by_id(goldens, "sourdough-lab")
    world = spec.experience.visual_world.model_copy(
        update={
            "bespoke": BespokeLayer(
                css="#capture-dialog { color: #ff0000; }",
                rationale="Recolour the capture dialog.",
            )
        }
    )
    experience = spec.experience.model_copy(update={"visual_world": world})
    with_layer = spec.model_copy(update={"experience": experience})

    compiler = FoundryCompiler()
    artifact = compiler.compile(with_layer, tmp_path / "rejected")
    html = artifact.app.read_text(encoding="utf-8")
    stylesheet = html.split("<style>", 1)[1].split("</style>", 1)[0]
    assert "#ff0000" not in stylesheet
    receipt = json.loads(artifact.receipt.read_text(encoding="utf-8"))
    assert receipt["experience"]["bespoke_layer"] == "none"
    assert receipt["experience"]["bespoke_rejections"]
    # What was asked for is still on the record in the spec the app carries,
    # so a dropped layer is visible rather than silent.
    assert "#capture-dialog" in html
    # The page itself is the page it would have been without the layer.
    assert compiler.render_stylesheet(with_layer) == compiler.render_stylesheet(spec)


def test_a_layer_does_not_break_determinism(goldens) -> None:
    spec = _by_id(goldens, "card-collector")
    world = spec.experience.visual_world.model_copy(
        update={"bespoke": BespokeLayer(css=GOOD_LAYER, rationale="Widen the binder.")}
    )
    experience = spec.experience.model_copy(update={"visual_world": world})
    with_layer = spec.model_copy(update={"experience": experience})
    compiler = FoundryCompiler()
    assert _digest(compiler.render_app(with_layer)) == _digest(compiler.render_app(with_layer))


# --------------------------------------------------------------------------
# B6: an approved look binds the build (the Lane C handshake, compiler side).
# --------------------------------------------------------------------------


def test_an_approved_look_binds_layout_type_room_motifs_and_colours(goldens) -> None:
    spec = _by_id(goldens, "sourdough-lab")
    look = LookBinding(
        look_id="low-tide",
        concept_id="tide-first",
        topology="canvas",
        typography_stack="mono_forward",
        density_scale="dense",
        token_overrides={"accent": "#1F6F8B", "radius_px": "2"},
        signature_elements=["progress_bar", "life_list"],
        bespoke=BespokeLayer(css=GOOD_LAYER, rationale="Wider cards for the board."),
        notes=["Keep the curve, drop the cards."],
    )
    bound = spec.model_copy(update={"look": look})
    compiler = FoundryCompiler()
    plan = compiler.experience_plan(bound)

    assert plan.topology == "canvas"
    assert plan.typography_stack == "mono_forward"
    assert plan.density_scale == "dense"
    assert plan.signature_elements == ("progress_bar", "life_list")
    assert plan.tokens["accent"] == "#1F6F8B"
    assert plan.tokens["radius_px"] == 2
    assert plan.look_id == "low-tide"

    html = compiler.render_app(bound)
    assert "--accent: #1F6F8B;" in html
    assert "--radius: 2px;" in html
    assert 'data-topology="canvas"' in html
    assert 'data-density="dense"' in html
    assert module._TOPOLOGY_CSS["canvas"] in html
    assert ".app .region {" in html

    # Nothing about the unbound build changed.
    assert compiler.experience_plan(spec).topology == "hub"


def test_a_partly_marked_look_only_binds_what_it_says(goldens) -> None:
    spec = _by_id(goldens, "japanese-study-coach")
    bound = spec.model_copy(
        update={
            "look": LookBinding(look_id="quiet-corridor", token_overrides={"accent": "#7A2E1E"})
        }
    )
    compiler = FoundryCompiler()
    plan = compiler.experience_plan(bound)
    assert plan.topology == "session"
    assert plan.typography_stack == "reading_serif"
    assert plan.tokens["accent"] == "#7A2E1E"
    assert plan.for_receipt()["token_overrides"] == {"accent": "#7A2E1E"}


# --------------------------------------------------------------------------
# Follow-up: what the difference gate and the other lanes asked for.
# --------------------------------------------------------------------------


def test_every_region_carries_its_kind_into_the_markup(goldens) -> None:
    """The 14 region kinds share 10 renderers. The attribute makes that visible."""
    assert 'data-region-kind="${esc(regionSpec.kind)}"' in RUNTIME
    assert 'data-region-emphasis="${esc(' in RUNTIME


def test_the_rail_is_a_banner_in_a_session_and_a_sidebar_everywhere_else() -> None:
    assert 'const railTag = topology === "session" ? "header" : "aside";' in RUNTIME
    assert '<${railTag} class="rail">' in RUNTIME


def test_a_forked_bundle_readme_names_its_parent(goldens) -> None:
    spec = _by_id(goldens, "card-collector")
    assert "Forked from" not in FoundryCompiler().render_readme(spec)
    forked = spec.model_copy(
        update={"remix": spec.remix.model_copy(update={"parent_spec": "sourdough-lab"})}
    )
    assert "Forked from sourdough-lab." in FoundryCompiler().render_readme(forked)


def test_what_the_app_was_put_together_from_is_rendered(goldens) -> None:
    """Nothing in the bundle stays present and unread."""
    for marker in (
        "remixSection",
        "remix.parent_spec",
        "remix.fragments",
        "remix.user_decisions",
        "look.borrowed_fragments",
        "look.notes",
    ):
        assert marker in RUNTIME, f"{marker} reaches the bundle but nothing renders it"
