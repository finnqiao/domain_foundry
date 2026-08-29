"""The local interest graph: what a practice is like, and what that means.

The idea atlas answers "where does this hobby live". This answers a different
question: "what is this hobby *like*, and what should the app be shaped like
because of it". They are separate on purpose. A hobby the atlas has never heard
of still has traits, and traits are what turn one sentence into three
structurally different app ideas rather than three names for the same log.

Two kinds of edge, and the difference matters:

* **Authored** edges are the rules, hand-written and cited. They live in
  ``trait_edges.yaml`` beside this module and never change because of a build.
* **Detected** edges are what one particular brief and one particular set of
  seeds turned out to match. Each one names the authored rule it fired and the
  seed it was read off, so a reader can check the reasoning.

``TraitEdge`` enforces that split: an authored edge must cite evidence, a
detected edge must name where it came from.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from domain_foundry_core.foundry.models import (
    NavigationTopology,
    SeedProvenance,
    SignatureElement,
    TraitEdge,
)

TRAIT_EDGES_FILENAME = "trait_edges.yaml"

# How many separate signals a rule needs before it counts as detected. One
# stray word is a coincidence; the point of a floor is that "time" appearing
# once in a birdwatching brief does not turn the app into a stopwatch.
_MATCH_FLOOR = 2

_WORD_RE = re.compile(r"[a-z0-9']+")


@dataclass(frozen=True)
class TraitSignals:
    """What makes a rule fire. Never evidence, only attention."""

    words: tuple[str, ...] = ()
    columns: tuple[str, ...] = ()


@dataclass(frozen=True)
class TraitRule:
    """One authored edge plus the signals that notice it."""

    edge: TraitEdge
    signals: TraitSignals = field(default_factory=TraitSignals)

    @property
    def id(self) -> str:
        return self.edge.id


class TraitGraph:
    """The merged rule set. An overlay rule shadows a shipped one by id."""

    def __init__(self, rules: Iterable[TraitRule]) -> None:
        self.rules: dict[str, TraitRule] = {rule.id: rule for rule in rules}

    def __len__(self) -> int:
        return len(self.rules)

    def get(self, edge_id: str) -> TraitRule | None:
        return self.rules.get(edge_id)

    @property
    def edges(self) -> list[TraitEdge]:
        return [rule.edge for rule in self.rules.values()]

    def topologies(self) -> set[str]:
        return {rule.edge.topology for rule in self.rules.values() if rule.edge.topology}


def bundled_trait_edges() -> Path:
    return Path(__file__).resolve().parent / TRAIT_EDGES_FILENAME


def _parse(path: Path) -> list[TraitRule]:
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        raise ValueError(f"{path}: trait edge file must be a mapping")
    rules: list[TraitRule] = []
    for item in raw.get("rules") or []:
        if not isinstance(item, dict) or "edge" not in item:
            raise ValueError(f"{path}: every rule needs an 'edge'")
        signals = item.get("signals") or {}
        rules.append(
            TraitRule(
                edge=TraitEdge.model_validate(item["edge"]),
                signals=TraitSignals(
                    words=tuple(str(word).casefold() for word in signals.get("words") or []),
                    columns=tuple(
                        str(column).casefold() for column in signals.get("columns") or []
                    ),
                ),
            )
        )
    return rules


def load_trait_graph(overlay: Path | None = None) -> TraitGraph:
    """Shipped rules, then the user's own, same id wins.

    The overlay is the same directory the idea atlas uses,
    ``~/.domain_foundry/atlas/``. Someone who knows their hobby better than the
    shipped rules do can say so, locally, without forking anything.
    """
    rules = _parse(bundled_trait_edges())
    if overlay is not None:
        candidate = Path(overlay) / TRAIT_EDGES_FILENAME
        if candidate.is_file():
            rules.extend(_parse(candidate))
    return TraitGraph(rules)


def validate_trait_graph(graph: TraitGraph) -> list[str]:
    """Structural checks a test or a lint can run over the rule set."""
    errors: list[str] = []
    for rule in graph.rules.values():
        edge = rule.edge
        if edge.origin != "authored":
            errors.append(f"{edge.id}: a shipped rule must be authored")
        if not edge.evidence_ids:
            errors.append(f"{edge.id}: an authored rule must cite evidence")
        if edge.topology is None:
            errors.append(f"{edge.id}: a rule with no structural consequence says nothing")
        if not (rule.signals.words or rule.signals.columns):
            errors.append(f"{edge.id}: a rule nothing can notice will never fire")
    return errors


# --------------------------------------------------------------------------- #
# Detection
# --------------------------------------------------------------------------- #


def _terms(value: str) -> set[str]:
    return set(_WORD_RE.findall(value.casefold()))


def _seed_columns(seeds: Iterable[SeedProvenance]) -> dict[str, list[str]]:
    """Column name to the seeds it appeared in."""
    found: dict[str, list[str]] = {}
    for seed in seeds:
        for column in seed.columns:
            found.setdefault(column.casefold(), []).append(seed.id)
    return found


def detect_traits(
    *,
    text: str = "",
    seeds: Sequence[SeedProvenance] = (),
    graph: TraitGraph | None = None,
) -> list[TraitEdge]:
    """Read the traits of a practice off the brief and off what the user keeps.

    A tide column in a spreadsheet is worth more than the word "tide" in a
    sentence, because the user has been recording it for a year. So a column
    match alone is enough, while loose words need to agree with each other.

    Every edge that comes back is ``detected``, cites the authored rule it fired
    so the reasoning can be checked, and names the seeds it was read off.
    """
    graph = graph or load_trait_graph()
    seeds = list(seeds)
    blob = " ".join(
        [text, *(seed.label for seed in seeds), *(" ".join(seed.columns) for seed in seeds)]
    )
    words = _terms(blob)
    lowered = blob.casefold()
    columns = _seed_columns(seeds)

    detected: list[tuple[int, TraitEdge]] = []
    for rule in graph.rules.values():
        hits = 0
        seed_ids: list[str] = []
        for column in rule.signals.columns:
            if column in columns:
                # A recorded column is a strong signal on its own.
                hits += _MATCH_FLOOR
                seed_ids.extend(columns[column])
        for word in rule.signals.words:
            if " " in word:
                if word in lowered:
                    hits += 1
            elif word in words:
                hits += 1
        if hits < _MATCH_FLOOR:
            continue
        detected.append(
            (
                hits,
                TraitEdge(
                    id=f"detected_{rule.edge.id}",
                    trait=rule.edge.trait,
                    consequence=rule.edge.consequence,
                    origin="detected",
                    topology=rule.edge.topology,
                    signature_elements=list(rule.edge.signature_elements),
                    # The authored rule this fired, so the reasoning is checkable,
                    # plus the rule's own citations.
                    evidence_ids=[rule.edge.id, *rule.edge.evidence_ids][:20],
                    seed_ids=list(dict.fromkeys(seed_ids))[:20],
                ),
            )
        )
    detected.sort(key=lambda pair: (-pair[0], pair[1].id))
    return [edge for _hits, edge in detected]


# --------------------------------------------------------------------------- #
# What detection is for
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class StructuralOption:
    """One shape a concept could take, and why.

    This is what the concept stage is handed. Three of these that differ in
    ``topology`` are three concepts that differ in structure, which is the whole
    reason the trait graph exists.
    """

    trait_id: str
    topology: NavigationTopology
    signature_elements: tuple[SignatureElement, ...]
    trait: str
    consequence: str

    def as_payload(self) -> dict[str, Any]:
        return {
            "trait_id": self.trait_id,
            "topology": self.topology,
            "signature_elements": list(self.signature_elements),
            "trait": self.trait,
            "consequence": self.consequence,
        }


def structural_options(traits: Sequence[TraitEdge], *, count: int = 3) -> list[StructuralOption]:
    """The distinct shapes the detected traits imply, strongest first.

    Distinct means distinct topology. Two traits that both want a session are
    one option, not two, because two concepts that navigate the same way are the
    same concept wearing different words.
    """
    options: list[StructuralOption] = []
    seen: set[str] = set()
    for edge in traits:
        if edge.topology is None or edge.topology in seen:
            continue
        seen.add(edge.topology)
        options.append(
            StructuralOption(
                trait_id=edge.id,
                topology=edge.topology,
                signature_elements=tuple(edge.signature_elements),
                trait=edge.trait,
                consequence=edge.consequence,
            )
        )
        if len(options) >= count:
            break
    return options


__all__ = [
    "TRAIT_EDGES_FILENAME",
    "StructuralOption",
    "TraitGraph",
    "TraitRule",
    "TraitSignals",
    "bundled_trait_edges",
    "detect_traits",
    "load_trait_graph",
    "structural_options",
    "validate_trait_graph",
]
