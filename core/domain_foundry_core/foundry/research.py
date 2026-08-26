"""Research adapters and licensed-corpus retrieval for Foundry proposals."""

from __future__ import annotations

import hashlib
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Protocol
from urllib.parse import urlparse

import httpx
import yaml
from pydantic import BaseModel, ConfigDict, Field

from domain_foundry_core.clock import now_iso

from .loader import DEFAULT_REGISTRY
from .models import EvidenceTier, SourceSnapshot

_WORD_RE = re.compile(r"[a-z0-9]{3,}")
_ALWAYS_RETRIEVE = {
    "postgresql_constraints",
    "postgresql_indexes",
    "sqlite_foreign_keys",
    "sqlite_query_planner",
    "w3c_prov",
    "govuk_design_principles",
    "wcag_22",
    "aria_apg",
    "ui_remix_paper",
    "owasp_llmsvs",
    "slsa",
    "spdx",
}


class ResearchModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


# How many matching domain exemplars survive the limit no matter how crowded the
# registry gets. Exactly one, and only the top-ranked: "matching" here is topic-token
# overlap, which is loose enough that a lifting source matches a sourdough plan on the
# single word "strength". Guaranteeing the best match satisfies the fail-closed check
# below without promoting an incidental one into a spec's evidence.
_VERTICAL_FLOOR = 1

ResearchText = Annotated[str, Field(min_length=1, max_length=1_200)]


class ResearchPlan(ResearchModel):
    interest: ResearchText
    desired_outcome: ResearchText
    practice_hypotheses: list[ResearchText] = Field(min_length=2, max_length=6)
    queries: list[ResearchText] = Field(min_length=3, max_length=8)
    vertical_keywords: list[ResearchText] = Field(min_length=2, max_length=12)
    artifact_questions: list[ResearchText] = Field(min_length=1, max_length=6)
    constraints: list[ResearchText] = Field(default_factory=list, max_length=20)


class ResearchCandidate(ResearchModel):
    source: SourceSnapshot
    excerpt: str
    query: str | None = None


class SearchProvider(Protocol):
    name: str

    def search(self, query: str, *, count: int = 5) -> list[ResearchCandidate]: ...


class ResearchUnavailable(RuntimeError):
    """No credible vertical evidence was available for the requested interest."""

    def __init__(self, plan: ResearchPlan, message: str) -> None:
        super().__init__(message)
        self.plan = plan


@dataclass(frozen=True)
class RetrievedKnowledge:
    registered: list[dict[str, object]]
    external: list[ResearchCandidate]
    tier: EvidenceTier = "reviewed_corpus"

    @property
    def source_ids(self) -> list[str]:
        return [str(item["id"]) for item in self.registered] + [
            item.source.id for item in self.external
        ]


def model_knowledge_candidates(plan: ResearchPlan) -> list[ResearchCandidate]:
    """The model's own recall, labelled as such at every layer.

    Not a retrieval: nothing was fetched, so there is no URL, no publisher that
    checked anything, and no approval. ``SourceSnapshot`` enforces that shape —
    ``tier=model_knowledge`` requires ``origin=model_recall``,
    ``status=reference_only`` and no URL — so a recall candidate cannot be
    mistaken downstream for something that was read.
    """
    retrieved = now_iso().split("T", 1)[0]
    topics = list(_terms(" ".join([plan.interest, *plan.vertical_keywords])))[:8]
    candidates: list[ResearchCandidate] = []
    for hypothesis in plan.practice_hypotheses:
        digest = hashlib.sha256(f"{plan.interest}|{hypothesis}".encode()).hexdigest()
        candidates.append(
            ResearchCandidate(
                source=SourceSnapshot(
                    id=f"model_recall_{digest[:16]}",
                    title=f"Model recall: {hypothesis}"[:240],
                    publisher="the configured language model",
                    url=None,
                    kind="model_recall",
                    tier="model_knowledge",
                    license="none-model-recall",
                    allowed_uses=["reference_facts", "paraphrase"],
                    status="reference_only",
                    origin="model_recall",
                    retrieved_at=retrieved,
                    freshness_days=1,
                    topics=topics or ["research"],
                ),
                excerpt=(
                    "Unverified recall from the configured model about this practice: "
                    f"{hypothesis}. Nothing was retrieved. Any claim drawn from this "
                    "candidate is the model's own knowledge, must be stated as unverified, "
                    "and must not be attributed to a publisher."
                )[:1200],
                query=None,
            )
        )
    return candidates


class KnowledgeRetriever:
    """Rank the maintained registry; external search stays behind an adapter."""

    def __init__(self, registry_path: Path = DEFAULT_REGISTRY) -> None:
        self.registry_path = registry_path

    def retrieve(
        self,
        plan: ResearchPlan,
        *,
        search: SearchProvider | None = None,
        registered_limit: int = 16,
        external_limit: int = 12,
        allow_model_knowledge: bool = False,
    ) -> RetrievedKnowledge:
        document = yaml.safe_load(self.registry_path.read_text(encoding="utf-8")) or {}
        sources = list(document.get("sources", []))
        terms = _terms(
            " ".join(
                [
                    plan.interest,
                    plan.desired_outcome,
                    *plan.practice_hypotheses,
                    *plan.vertical_keywords,
                ]
            )
        )
        ranked: list[tuple[int, dict[str, object]]] = []
        for source in sources:
            haystack = _terms(
                " ".join(
                    [
                        str(source.get("title") or ""),
                        str(source.get("publisher") or ""),
                        *[str(topic) for topic in source.get("topics", [])],
                    ]
                )
            )
            overlap = len(terms & haystack)
            score = overlap * 10
            if source.get("id") in _ALWAYS_RETRIEVE:
                score += 3
            if source.get("tier") in {"authoritative", "domain_exemplar"}:
                score += 1
            ranked.append((score, source))
        ranked.sort(key=lambda pair: (-pair[0], str(pair[1].get("id"))))
        scored = [source for score, source in ranked if score > 0]
        # Two kinds of evidence are guaranteed rather than merely favoured, because
        # both are load-bearing downstream and rank alone protects neither once the
        # registry grows.
        #
        # The cross-cutting slate: a domain source sharing one incidental token with
        # the interest ("tasting_notes" against a sourdough plan) could evict
        # provenance, accessibility, or remix guidance past the limit, and the spec
        # then failed closed with an opaque "cited unprovided sources".
        #
        # The vertical evidence: the fail-closed check below asks whether any matching
        # domain exemplar survived. Reserving the slate first could starve exactly the
        # source that check exists to find, turning a coverage gap into a false
        # "no reviewed vertical evidence".
        guaranteed = [source for source in scored if source.get("id") in _ALWAYS_RETRIEVE]
        vertical_matches = [
            source
            for source in scored
            if source.get("tier") == "domain_exemplar"
            and _terms(" ".join(_source_topics(source))) & terms
        ]
        keep = {str(source.get("id")) for source in guaranteed}
        keep.update(str(source.get("id")) for source in vertical_matches[:_VERTICAL_FLOOR])
        for source in scored:
            if len(keep) >= registered_limit:
                break
            keep.add(str(source.get("id")))
        registered = [source for source in scored if str(source.get("id")) in keep]

        external: list[ResearchCandidate] = []
        if search is not None:
            seen: set[str] = set()
            for query in plan.queries:
                for candidate in search.search(query, count=4):
                    # A retrieved candidate dedupes on its URL. ``url`` is
                    # optional since the model_knowledge tier has none, so fall
                    # back to the id rather than collapsing every such candidate
                    # into one on a shared ``None``.
                    key = candidate.source.url or candidate.source.id
                    if key in seen:
                        continue
                    seen.add(key)
                    external.append(candidate)
                    if len(external) >= external_limit:
                        break
                if len(external) >= external_limit:
                    break

        vertical = [
            source
            for source in registered
            if source.get("tier") == "domain_exemplar"
            and _terms(" ".join(_source_topics(source))) & terms
        ]
        if not vertical and not external:
            # ADR-010. The gate stays closed unless the caller opened it by name.
            # ``foundry propose`` never does: a user who asked for a researched
            # specification gets one or gets nothing.
            if not allow_model_knowledge:
                raise ResearchUnavailable(
                    plan,
                    "No reviewed vertical evidence matched this interest. Configure the Brave "
                    "research adapter or supply a reviewed source packet; Domain Foundry will not "
                    "present a generic scaffold as researched output.",
                )
            return RetrievedKnowledge(
                registered=registered,
                external=model_knowledge_candidates(plan),
                tier="model_knowledge",
            )
        return RetrievedKnowledge(
            registered=registered,
            external=external,
            tier="reviewed_corpus" if vertical else "live_search",
        )


class BraveSearchProvider:
    """Optional web-discovery adapter. Results are reference-only until reviewed."""

    name = "brave"

    def __init__(
        self,
        *,
        api_key: str | None = None,
        endpoint: str = "https://api.search.brave.com/res/v1/web/search",
        timeout: float = 20.0,
    ) -> None:
        self.api_key = api_key or os.environ.get("BRAVE_SEARCH_API_KEY")
        self.endpoint = endpoint
        self.timeout = timeout

    def search(self, query: str, *, count: int = 5) -> list[ResearchCandidate]:
        if not self.api_key:
            raise ResearchUnavailable(
                ResearchPlan(
                    interest=query,
                    desired_outcome="Research the requested product",
                    practice_hypotheses=["Unknown practice", "Unknown artifacts"],
                    queries=[query, f"{query} open source", f"{query} data model"],
                    vertical_keywords=["research", "domain"],
                    artifact_questions=["What artifacts already exist?"],
                ),
                "BRAVE_SEARCH_API_KEY is not configured.",
            )
        response = httpx.get(
            self.endpoint,
            headers={
                "Accept": "application/json",
                "X-Subscription-Token": self.api_key,
            },
            params={"q": query, "count": max(1, min(count, 10)), "safesearch": "moderate"},
            timeout=self.timeout,
        )
        response.raise_for_status()
        results = (response.json().get("web") or {}).get("results") or []
        candidates: list[ResearchCandidate] = []
        retrieved = now_iso().split("T", 1)[0]
        for result in results:
            url = str(result.get("url") or "")
            parsed = urlparse(url)
            if parsed.scheme != "https" or not parsed.hostname:
                continue
            source_id = "web_" + hashlib.sha256(url.encode("utf-8")).hexdigest()[:16]
            excerpt = re.sub(r"<[^>]+>", " ", str(result.get("description") or ""))
            excerpt = re.sub(r"\s+", " ", excerpt).strip()[:1200]
            candidates.append(
                ResearchCandidate(
                    source=SourceSnapshot(
                        id=source_id,
                        title=str(result.get("title") or parsed.hostname)[:240],
                        publisher=parsed.hostname,
                        url=url,
                        kind="web_search_result",
                        tier="product_reference",
                        license="unknown-reference",
                        allowed_uses=["reference_facts", "paraphrase"],
                        status="reference_only",
                        retrieved_at=retrieved,
                        freshness_days=90,
                        topics=list(_terms(query))[:8] or ["research"],
                    ),
                    excerpt=excerpt,
                    query=query,
                )
            )
        return candidates


def _terms(value: str) -> set[str]:
    return set(_WORD_RE.findall(value.lower()))


def _source_topics(source: dict[str, object]) -> list[str]:
    topics = source.get("topics")
    return [str(item) for item in topics] if isinstance(topics, list) else []


__all__ = [
    "BraveSearchProvider",
    "KnowledgeRetriever",
    "ResearchCandidate",
    "ResearchPlan",
    "ResearchUnavailable",
    "RetrievedKnowledge",
    "SearchProvider",
    "model_knowledge_candidates",
]
