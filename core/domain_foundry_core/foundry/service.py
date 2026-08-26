"""Workspace persistence and orchestration for the Foundry HTTP surface."""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

import yaml

from domain_foundry_core.ids import new_ulid
from domain_foundry_core.llm.provider import build_tiered_provider

from .compiler import FoundryCompiler
from .loader import DEFAULT_REGISTRY, load_golden_specs
from .models import RemixSelection
from .pipeline import AcceptanceTask, FoundryPipeline, FoundryProposal, ProposedFoundry
from .research import BraveSearchProvider

_PROPOSAL_ID_RE = re.compile(r"^[0-9A-HJKMNP-TV-Z]{26}$")


class FoundryService:
    def __init__(self, home: Path) -> None:
        self.home = home.resolve()
        self.root = self.home / "foundry"
        self.proposals = self.root / "proposals"
        self.apps = self.root / "apps"

    def list_goldens(self) -> list[dict[str, Any]]:
        return [self._summary(spec.model_dump(mode="json")) for spec in load_golden_specs()]

    def get_golden(self, spec_id: str) -> dict[str, Any]:
        spec = next((item for item in load_golden_specs() if item.id == spec_id), None)
        if spec is None:
            raise KeyError(f"unknown golden FoundrySpec: {spec_id}")
        payload = spec.model_dump(mode="json")
        payload["owned_app_html"] = FoundryCompiler().render_app(spec)
        return payload

    def propose(
        self,
        goal: str,
        *,
        artifacts: list[str],
        constraints: list[str],
        acceptance_tasks: list[AcceptanceTask],
        use_web_research: bool,
    ) -> tuple[str, ProposedFoundry]:
        provider = build_tiered_provider(self.home)
        if not provider.has_live_keys():
            raise RuntimeError(
                "Foundry design needs a configured reasoning model. Run domain-foundry setup; "
                "the offline keyword scaffold is intentionally not used for this workflow."
            )
        search = None
        if use_web_research and os.environ.get("BRAVE_SEARCH_API_KEY"):
            search = BraveSearchProvider()
        result = FoundryPipeline(provider, search=search).propose(
            goal,
            artifacts=artifacts,
            constraints=constraints,
            acceptance_tasks=acceptance_tasks,
        )
        proposal_id = new_ulid()
        self.proposals.mkdir(parents=True, exist_ok=True)
        result.proposal.dump(self.proposals / f"{proposal_id}.yaml")
        return proposal_id, result

    def complete(self, proposal_id: str, remix: RemixSelection) -> dict[str, Any]:
        proposal_path = self._proposal_path(proposal_id)
        if not proposal_path.is_file():
            raise KeyError(f"unknown foundry proposal: {proposal_id}")
        provider = build_tiered_provider(self.home)
        if not provider.has_live_keys():
            raise RuntimeError("Foundry completion needs the configured reasoning model.")
        proposal = FoundryProposal.load(proposal_path)
        spec = FoundryPipeline(provider).complete(proposal, remix)
        app_root = self.apps / proposal_id
        artifact = FoundryCompiler().compile(spec, app_root)
        return {
            "proposal_id": proposal_id,
            "spec": spec.model_dump(mode="json"),
            "owned_app_html": artifact.app.read_text(encoding="utf-8"),
            "app_url": f"/api/foundry/apps/{proposal_id}",
            "artifacts": {
                "app": str(artifact.app),
                "schema": str(artifact.schema),
                "spec": str(artifact.spec),
                "evidence": str(artifact.evidence),
                "receipt": str(artifact.receipt),
            },
        }

    def proposal_sources(self, proposal: FoundryProposal) -> list[dict[str, Any]]:
        registry = yaml.safe_load(DEFAULT_REGISTRY.read_text(encoding="utf-8")) or {}
        wanted = set(proposal.source_ids)
        records = [
            item for item in registry.get("sources", []) if item.get("id") in wanted
        ]
        registered = {str(item.get("id")) for item in records}
        records.extend(
            item.model_dump(mode="json")
            for item in proposal.source_snapshots
            if item.id not in registered
        )
        return records

    def app_path(self, proposal_id: str) -> Path:
        self._proposal_path(proposal_id)
        path = (self.apps / proposal_id / "app.html").resolve()
        if not path.is_relative_to(self.apps.resolve()):
            raise ValueError("invalid proposal id")
        if not path.is_file():
            raise KeyError(f"unknown compiled foundry app: {proposal_id}")
        return path

    def _proposal_path(self, proposal_id: str) -> Path:
        if not _PROPOSAL_ID_RE.fullmatch(proposal_id):
            raise ValueError("invalid proposal id")
        return self.proposals / f"{proposal_id}.yaml"

    @staticmethod
    def _summary(spec: dict[str, Any]) -> dict[str, Any]:
        experience = spec["experience"]
        return {
            "id": spec["id"],
            "title": spec["title"],
            "interest": spec["research"]["interest"],
            "desired_outcome": spec["research"]["desired_outcome"],
            "concepts": [
                {
                    "id": item["id"],
                    "title": item["title"],
                    "thesis": item["thesis"],
                    "primary_loop": item["primary_loop"],
                }
                for item in spec["concepts"]
            ],
            "selected_concept": spec["remix"]["selected_concept"],
            "visual_world": experience["visual_world"],
            "topology": experience["navigation"]["topology"],
            "entities": len(spec["domain"]["entities"]),
            "views": len(experience["views"]),
            "source_count": len(spec["source_ids"]),
        }


__all__ = ["FoundryService"]
