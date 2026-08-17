"""Atlas node and edge contracts. Jobs listed here are the compiler alphabet."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

NodeKind = Literal["bucket", "practice", "idea"]
Provenance = Literal["world", "foundry", "both"]
EdgeRel = Literal["child", "adjacent", "expands_to", "analog_of"]

JOBS: tuple[str, ...] = (
    "catalog",
    "event_log",
    "improvement",
    "atlas",
    "media_dex",
    "lab",
    "practice",
    "graph",
    "plan",
)
JobName = Literal[
    "catalog",
    "event_log",
    "improvement",
    "atlas",
    "media_dex",
    "lab",
    "practice",
    "graph",
    "plan",
]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class WorldAnalog(_Strict):
    name: str
    one_liner: str


class AtlasNode(_Strict):
    id: str
    kind: NodeKind
    title: str
    aliases: list[str] = Field(default_factory=list)
    pitch: str = ""
    jobs: list[str] = Field(default_factory=list)
    provenance: Provenance | None = None
    world_analogs: list[WorldAnalog] = Field(default_factory=list)
    analog_pack: str | None = None
    domain_slug: str | None = None
    identity_hint: str | None = None
    example: str = ""
    jargon: list[str] = Field(default_factory=list)

    @field_validator("id")
    @classmethod
    def _id_ok(cls, value: str) -> str:
        if not value or any(ch in value for ch in " \t\n"):
            raise ValueError(f"bad atlas id {value!r}")
        return value

    @field_validator("jobs")
    @classmethod
    def _jobs_known(cls, value: list[str]) -> list[str]:
        unknown = [j for j in value if j not in JOBS]
        if unknown:
            raise ValueError(f"unknown jobs {unknown}")
        return list(dict.fromkeys(value))

    def terms(self) -> list[str]:
        out = [self.id, self.title, *(self.aliases or [])]
        if self.domain_slug:
            out.append(self.domain_slug)
        out.extend(part for part in self.id.replace("-", ".").split(".") if part)
        out.extend(self.jargon or [])
        return out


class AtlasEdge(_Strict):
    source: str = Field(alias="from")
    target: str = Field(alias="to")
    rel: EdgeRel


class AtlasGraph:
    """Merged node/edge index. Overlay nodes shadow shipped ids."""

    def __init__(self, nodes: list[AtlasNode], edges: list[AtlasEdge]) -> None:
        self.nodes: dict[str, AtlasNode] = {n.id: n for n in nodes}
        self.edges: list[AtlasEdge] = list(edges)
        self._children: dict[str, list[str]] = {}
        self._parents: dict[str, list[str]] = {}
        self._adjacent: dict[str, list[str]] = {}
        self._expands: dict[str, list[str]] = {}
        for edge in self.edges:
            if edge.source not in self.nodes or edge.target not in self.nodes:
                continue
            if edge.rel == "child":
                self._children.setdefault(edge.source, []).append(edge.target)
                self._parents.setdefault(edge.target, []).append(edge.source)
            elif edge.rel == "adjacent":
                self._adjacent.setdefault(edge.source, []).append(edge.target)
                self._adjacent.setdefault(edge.target, []).append(edge.source)
            elif edge.rel == "expands_to":
                self._expands.setdefault(edge.source, []).append(edge.target)

    def get(self, node_id: str) -> AtlasNode | None:
        return self.nodes.get(node_id)

    def children(self, node_id: str) -> list[AtlasNode]:
        return [self.nodes[i] for i in self._children.get(node_id, []) if i in self.nodes]

    def parents(self, node_id: str) -> list[AtlasNode]:
        return [self.nodes[i] for i in self._parents.get(node_id, []) if i in self.nodes]

    def adjacent(self, node_id: str) -> list[AtlasNode]:
        seen: list[str] = []
        for i in self._adjacent.get(node_id, []):
            if i not in seen and i in self.nodes:
                seen.append(i)
        return [self.nodes[i] for i in seen]

    def expands_to(self, node_id: str) -> list[AtlasNode]:
        return [self.nodes[i] for i in self._expands.get(node_id, []) if i in self.nodes]

    def ideas_at(self, node_id: str) -> list[AtlasNode]:
        return [n for n in self.children(node_id) if n.kind == "idea"]

    def practices_at(self, node_id: str) -> list[AtlasNode]:
        return [n for n in self.children(node_id) if n.kind == "practice"]

    def buckets(self) -> list[AtlasNode]:
        return [n for n in self.nodes.values() if n.kind == "bucket"]

    def breadcrumb(self, node_id: str) -> list[AtlasNode]:
        chain: list[AtlasNode] = []
        current = self.get(node_id)
        guard = 0
        while current is not None and guard < 8:
            chain.append(current)
            parents = self.parents(current.id)
            current = parents[0] if parents else None
            guard += 1
        chain.reverse()
        return chain

    def to_card(self, node: AtlasNode, *, highlighted: bool = False) -> dict[str, Any]:
        card: dict[str, Any] = {
            "id": node.id,
            "kind": node.kind,
            "title": node.title,
            "pitch": node.pitch,
            "aliases": list(node.aliases),
        }
        if node.kind == "idea":
            card.update(
                {
                    "jobs": list(node.jobs),
                    "provenance": node.provenance,
                    "world_analogs": [a.model_dump() for a in node.world_analogs],
                    "analog_pack": node.analog_pack,
                    "domain_slug": node.domain_slug,
                    "identity_hint": node.identity_hint,
                    "example": node.example,
                    "highlighted": highlighted,
                }
            )
        return card
