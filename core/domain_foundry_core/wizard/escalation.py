"""ADR-010: drive the Foundry pipeline from inside a conversational create.

``bridge.py`` is the pure projection: ``FoundrySpec`` in, ``ShortlistModel``
out, no I/O. This module is everything around it: turn two elicited sentences
into acceptance tasks, hand the atlas over as a *prior* rather than an answer,
run ``propose(concept_count=1)`` → ``complete()`` → ``spec_to_shortlist()``, and
write the receipts somewhere a technical user can open them.

It is deliberately separate from ``engine.py``. The engine owns the state
machine and decides *whether* to escalate; this owns *what escalating does*, so
a pipeline contract change lands in one file with no session or harness in it.
The import direction stays one-way: ``wizard`` imports ``foundry``, never the
reverse (``tests/unit/test_wizard_foundry_bridge.py`` asserts the second half).

Nothing here calls a model on its own account. The provider is passed in, and
the caller has already established that it has live keys. A create with no key
never reaches this module at all.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from domain_foundry_core.foundry.models import (
    FoundrySpec,
    RemixSelection,
    evidence_tier_label,
)
from domain_foundry_core.foundry.pipeline import (
    AcceptanceTask,
    BudgetExhausted,
    FoundryPipeline,
    FoundryProposal,
    PipelineError,
)
from domain_foundry_core.foundry.research import ResearchUnavailable, SearchProvider
from domain_foundry_core.llm.provider import LLMProvider
from domain_foundry_core.wizard.bridge import spec_to_shortlist
from domain_foundry_core.wizard.shortlist import ShortlistExample, ShortlistModel

# ADR-010: the wizard asks a hobbyist for a sentence they would type, not for an
# observable outcome. The *expectation* is therefore mechanical and identical for
# both sentences — the user authored the input, which is the half that matters,
# because it is the half the generator is forbidden to author for itself.
ACCEPTANCE_EXPECTED = "files into the app and appears in its main view"

# How many sentences the bridge needs before it will run. Both become
# ``AcceptanceTask``s; only the first is allowed anywhere near the design.
REQUIRED_SAMPLES = 2

# Bounds on the prior. It is a hint, and an unbounded hint starts behaving like
# an instruction — a 40-term jargon list would dominate a research plan.
MAX_PRIOR_IDEAS = 4
MAX_PRIOR_TERMS = 24
MAX_PRIOR_ANALOGS = 6

_PRIOR_NOTE = (
    "A hobby catalogue's rough guess at this interest, supplied as a starting "
    "hint. It is unreviewed and frequently wrong about unindexed hobbies. Verify, "
    "widen, or discard it; do not treat it as evidence and do not cite it."
)


class BridgeUnavailable(RuntimeError):
    """The bridge was eligible and did not deliver.

    ``reason`` is the sentence the wizard puts in front of the user. It exists
    because a misconfigured provider must never look identical to having no key.
    """

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class BridgeRun:
    """Everything one escalation produced, ready to compile and to persist."""

    goal: str
    proposal: FoundryProposal
    spec: FoundrySpec
    shortlist: ShortlistModel
    seed: str
    held_out: str
    spent_usd: float | None = None

    @property
    def evidence_tier(self) -> str:
        return self.spec.evidence_tier or "fallback_demo"

    @property
    def evidence_label(self) -> str:
        return evidence_tier_label(self.spec.evidence_tier)


# --------------------------------------------------------------------------- #
# Inputs
# --------------------------------------------------------------------------- #


def acceptance_tasks(samples: list[str]) -> list[AcceptanceTask]:
    """The two elicited sentences, verbatim, as the run's independent judge.

    ``input`` is exactly what the user typed. It is trimmed only of surrounding
    whitespace and never rewritten, so the pipeline's rule that the generator
    cannot author its own criteria still holds. Only the interface for
    collecting them changed.
    """
    usable = [text.strip() for text in samples if text and text.strip()]
    if len(usable) < REQUIRED_SAMPLES:
        raise BridgeUnavailable(
            "I need two sentences you'd actually log before I can research this; "
            f"I have {len(usable)}."
        )
    return [
        AcceptanceTask(input=text[:2_000], expected=ACCEPTANCE_EXPECTED)
        for text in usable[:REQUIRED_SAMPLES]
    ]


def atlas_prior(
    *,
    goal: str,
    neighborhood: dict[str, Any] | None,
    ideas: list[Any],
    samples: list[str],
) -> dict[str, Any]:
    """Demote the atlas to a prior: neighbourhood, cards, analogs, jargon.

    Everything here is a guess, and the research stage may throw all of it
    away. The user's own sentences ride along because they are the one part of the payload
    that is not a guess.
    """
    neighborhood = neighborhood or {}
    cards: list[dict[str, Any]] = []
    analogs: list[dict[str, str]] = []
    jargon: list[str] = []
    vocabulary: list[str] = []
    for idea in ideas[:MAX_PRIOR_IDEAS]:
        cards.append(
            {
                "title": getattr(idea, "title", ""),
                "pitch": getattr(idea, "pitch", ""),
                "jobs": list(getattr(idea, "jobs", []) or []),
                "example": getattr(idea, "example", ""),
            }
        )
        for analog in getattr(idea, "world_analogs", []) or []:
            analogs.append(
                {
                    "name": getattr(analog, "name", ""),
                    "one_liner": getattr(analog, "one_liner", ""),
                }
            )
        jargon.extend(str(term) for term in getattr(idea, "jargon", []) or [])
        vocabulary.extend(str(term) for term in getattr(idea, "vocabulary", []) or [])

    prior: dict[str, Any] = {
        "note": _PRIOR_NOTE,
        "goal": goal,
        "catalogue_node": neighborhood.get("cursor"),
        "catalogue_had_no_match": bool(neighborhood.get("unindexed")),
        "breadcrumb": [
            str(step.get("title") or step.get("id") or "")
            for step in (neighborhood.get("breadcrumb") or [])
            if isinstance(step, dict)
        ],
        "idea_cards": cards,
        "world_analogs": _unique(analogs, key=lambda item: item["name"])[:MAX_PRIOR_ANALOGS],
        "jargon": _unique_terms(jargon)[:MAX_PRIOR_TERMS],
        "vocabulary": _unique_terms(vocabulary)[:MAX_PRIOR_TERMS],
        "user_sentences": [text.strip() for text in samples if text and text.strip()],
    }
    return prior


# --------------------------------------------------------------------------- #
# The run
# --------------------------------------------------------------------------- #


def run_bridge(
    *,
    goal: str,
    samples: list[str],
    provider: LLMProvider,
    prior: dict[str, Any] | None = None,
    meter: Any | None = None,
    search: SearchProvider | None = None,
) -> BridgeRun:
    """Research ``goal`` and project the result onto the wizard's shortlist.

    Raises ``BridgeUnavailable``, and only that, for every way this can fail,
    so the caller has exactly one thing to catch and exactly one sentence to
    show. Budget exhaustion, an unreachable research provider, a provider error
    and a spec that will not validate all arrive here as a stated reason.
    """
    tasks = acceptance_tasks(samples)
    seed, held_out = tasks[0].input, tasks[1].input

    pipeline = FoundryPipeline(
        provider,
        search=search,
        meter=meter,
        # ADR-010: the bridge may fall to model recall because the alternative
        # for an unindexed hobby is the keyword scaffold, which is strictly worse
        # and says nothing about its own provenance. It is named everywhere.
        allow_model_knowledge=True,
    )

    try:
        proposed = pipeline.propose(
            goal,
            acceptance_tasks=tasks,
            concept_count=1,
            prior=prior,
        )
        proposal = proposed.proposal
        remix = RemixSelection(
            selected_concept=proposal.concepts[0].id,
            fragments=[],
            user_decisions=[f"conversational create: {goal}"[:2_000]],
        )
        spec = pipeline.complete(proposal, remix)
    except BudgetExhausted as exc:
        raise BridgeUnavailable(
            f"the daily cost cap was reached before the {exc.stage} stage"
        ) from exc
    except ResearchUnavailable as exc:
        raise BridgeUnavailable(f"research was unavailable: {exc}") from exc
    except PipelineError as exc:
        raise BridgeUnavailable(f"the research pipeline refused its own output: {exc}") from exc
    except Exception as exc:  # noqa: BLE001 - every failure becomes one sentence
        raise BridgeUnavailable(f"{type(exc).__name__}: {exc}") from exc

    try:
        shortlist = seeded_shortlist(spec, goal=goal, seed=seed)
    except Exception as exc:  # noqa: BLE001
        raise BridgeUnavailable(
            f"the researched spec would not project onto a pack: "
            f"{type(exc).__name__}: {exc}"
        ) from exc

    return BridgeRun(
        goal=goal,
        proposal=proposal,
        spec=spec,
        shortlist=shortlist,
        seed=seed,
        held_out=held_out,
        spent_usd=getattr(meter, "spent_usd", None),
    )


def seeded_shortlist(spec: FoundrySpec, *, goal: str, seed: str) -> ShortlistModel:
    """The projection, plus the first elicited sentence as a routing example.

    ``spec_to_shortlist`` is untouched and stays a pure function of the spec.
    The seed is added here because ADR-010 gives the first sentence a job the
    spec knows nothing about: it becomes a routing example, which means the
    existing dry-run gate has to route the user's own words before this pack is
    allowed to activate. The second sentence is never added. It is the held-out
    check, and a check the design was shown is not a check.
    """
    shortlist = spec_to_shortlist(spec, goal=goal)
    text = (seed or "").strip()
    if not text:
        return shortlist
    already = {example.text.strip().lower() for example in shortlist.examples}
    if text.lower() in already:
        return shortlist
    seeded = ShortlistExample(text=text[:180], object=shortlist.objects[0], fields={})
    return shortlist.model_copy(update={"examples": [seeded, *shortlist.examples]})


# --------------------------------------------------------------------------- #
# Receipts
# --------------------------------------------------------------------------- #


def persist_artifacts(pack_root: Path, run: BridgeRun) -> Path:
    """Write ``<pack>/foundry/``, which is every step of the run, openable.

    A bridged pack claims to have been researched. This is where that claim is
    checkable: the spec it was built from, the proposal that produced it, the
    evidence with its tier, and the per-stage receipts naming provider, model
    and token counts.
    """
    root = Path(pack_root) / "foundry"
    root.mkdir(parents=True, exist_ok=True)
    spec = run.spec
    proposal = run.proposal

    _write_yaml(root / "spec.yaml", spec.model_dump(mode="json"))
    _write_yaml(root / "proposal.yaml", proposal.model_dump(mode="json"))
    _write_json(
        root / "evidence.json",
        {
            "evidence_tier": run.evidence_tier,
            "evidence_label": run.evidence_label,
            "research_provider": proposal.receipt.research_provider,
            "source_ids": list(spec.source_ids),
            "source_snapshots": [item.model_dump(mode="json") for item in spec.source_snapshots],
            "evidence": [item.model_dump(mode="json") for item in spec.evidence],
        },
    )
    _write_json(
        root / "receipts.json",
        {
            "pipeline_version": spec.generation.pipeline_version if spec.generation else None,
            "generated_at": spec.generation.generated_at if spec.generation else None,
            "evidence_tier": run.evidence_tier,
            "evidence_label": run.evidence_label,
            "research_provider": proposal.receipt.research_provider,
            "concept_count": len(spec.concepts),
            "remix_decisions": list(spec.remix.user_decisions),
            "acceptance_tasks": [item.model_dump() for item in proposal.acceptance_tasks],
            "held_out": run.held_out,
            "spent_usd": run.spent_usd,
            "stages": [
                item.model_dump(mode="json")
                for item in (spec.generation.stages if spec.generation else [])
            ],
        },
    )
    _write_json(root / "shortlist.json", run.shortlist.model_dump(mode="json"))
    (root / "README.md").write_text(_readme(run), encoding="utf-8")
    return root


def _readme(run: BridgeRun) -> str:
    return "\n".join(
        [
            f"# How {run.spec.title} was made",
            "",
            f"Goal, in your words: {run.goal}",
            "",
            f"Evidence: **{run.evidence_tier}**. {run.evidence_label}.",
            "",
            "| File | What it is |",
            "|---|---|",
            "| `proposal.yaml` | The research plan, the sources it drew on, the evidence "
            "it cited, and the single concept it committed to. |",
            "| `spec.yaml` | The full FoundrySpec: domain model, experience contract, "
            "evaluation cases. |",
            "| `evidence.json` | Every cited claim with its source and evidence tier. |",
            "| `receipts.json` | Per-stage provider, model, and token counts. |",
            "| `shortlist.json` | The projection of the spec onto this pack: objects, "
            "fields, jargon, routing examples. |",
            "",
            "The two sentences you gave are the acceptance tasks in `receipts.json`. "
            "The first shaped the design and is a routing example in this pack. The "
            "second was held out of all of it and replayed once the pack existed.",
            "",
        ]
    )


def _write_yaml(path: Path, payload: Any) -> None:
    path.write_text(
        yaml.safe_dump(payload, sort_keys=False, allow_unicode=True), encoding="utf-8"
    )


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )


def _unique(items: list[Any], *, key: Any) -> list[Any]:
    seen: set[Any] = set()
    out: list[Any] = []
    for item in items:
        marker = key(item)
        if not marker or marker in seen:
            continue
        seen.add(marker)
        out.append(item)
    return out


def _unique_terms(terms: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for term in terms:
        low = term.strip().lower()
        if not low or low in seen:
            continue
        seen.add(low)
        out.append(term.strip())
    return out


__all__ = [
    "ACCEPTANCE_EXPECTED",
    "REQUIRED_SAMPLES",
    "BridgeRun",
    "BridgeUnavailable",
    "acceptance_tasks",
    "atlas_prior",
    "persist_artifacts",
    "run_bridge",
    "seeded_shortlist",
]
