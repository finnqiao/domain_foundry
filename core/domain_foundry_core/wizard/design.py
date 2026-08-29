"""LLM-assisted domain design via shortlist → compile → load_pack.

Design is one deliberate call that returns a field shortlist. The harness
compiles it into a pack. Callers fall back to a labeled simple log when this
raises :class:`DesignError`.
"""

from __future__ import annotations

import copy
import json
import shutil
import tempfile
from pathlib import Path
from typing import Any

from domain_foundry_core.llm.provider import LLMProvider
from domain_foundry_core.packs.loader import load_pack
from domain_foundry_core.wizard import blueprint as bp
from domain_foundry_core.wizard.shortlist import (
    DesignLintError,
    ShortlistModel,
    compile_shortlist,
    lint_shortlist,
    shortlist_schema,
)


class DesignError(RuntimeError):
    """A model response could not become a valid pack blueprint."""


class LLMBlueprintDesigner:
    """Design a pack: shortlist JSON → lint → compile → load_pack."""

    def design(
        self,
        goal: str,
        *,
        llm: LLMProvider,
        tier: str = "sota",
        jobs: list[str] | None = None,
    ) -> dict[str, Any]:
        last_error: str | None = None
        for attempt in range(2):
            try:
                shortlist = self._request_shortlist(
                    goal, llm=llm, tier=tier, feedback=last_error, jobs=jobs
                )
                errors = lint_shortlist(shortlist, goal=goal)
                if errors:
                    last_error = "; ".join(errors)
                    if attempt == 0:
                        continue
                    raise DesignLintError(last_error)
                blueprint = compile_shortlist(shortlist, goal=goal)
                blueprint["archetype"] = "llm"
                blueprint["goal"] = goal
                blueprint["agent"] = bp.build_agent_spec(blueprint)
                self._round_trip(blueprint)
                return blueprint
            except DesignError:
                raise
            except Exception as exc:
                last_error = str(exc)
                if attempt == 0:
                    continue
                raise DesignError(f"design failed: {exc}") from exc
        raise DesignError(last_error or "design failed")

    def _request_shortlist(
        self,
        goal: str,
        *,
        llm: LLMProvider,
        tier: str,
        feedback: str | None,
        jobs: list[str] | None = None,
    ) -> ShortlistModel:
        jobs = jobs or []
        split = "catalog" in jobs and "event_log" in jobs
        system = (
            "You design a shortlist of fields for a personal app, not a generic log. "
            "Output ONLY JSON matching the schema. "
            + (
                "Split a catalog (identity of the thing) from events (when it happened). "
                if split
                else "Prefer ONE object unless catalog+event is clearly needed. "
            )
            + "Pick 5 to 8 key fields a real person would log: identity, when, measures, "
            "a few enums. Not title/rating/amount. Every example must contain a word "
            "unique to its object. Include jargon and ≥10 example utterances "
            "(≥3 without the interest name) with expected field maps."
        )
        from domain_foundry_core.wizard.jobs import analog_few_shots as job_shots

        payload: dict[str, Any] = {
            "FEW_SHOT_EXAMPLES": job_shots(goal),
            "GOAL": goal,
            "JOBS": jobs,
            "REQUIREMENTS": [
                "5–8 fields per object; honor JOBS (catalog+event split, location, photos, measures)",
                "exactly one identity field per object (not 'title' unless books/films)",
                "≥10 examples with fields; ≥3 omit the interest name",
                "each example includes a distinctive object word so keyword routing can file it",
                "jargon list with domain vocabulary",
            ],
        }
        if feedback:
            payload["PREVIOUS_ERRORS"] = feedback
            payload["REQUIREMENTS"].append("Fix every previous error.")
        try:
            result = llm.complete_json(
                system=system,
                user=json.dumps(payload, ensure_ascii=False),
                schema=shortlist_schema(),
                tier=tier,
            )
            return ShortlistModel.model_validate(result.data)
        except Exception as exc:
            raise DesignError(f"shortlist failed: {exc}") from exc

    def _round_trip(self, blueprint: dict[str, Any]) -> None:
        """Write + validate; drop self-inconsistent routing examples once.

        Models often emit example phrases that L1 cannot yet match. Those are
        teachable later. They must not force a silent scaffold fallback when
        the schema itself is sound.
        """
        from domain_foundry_core.packs.loader import PackValidationError

        tmp = Path(tempfile.mkdtemp(prefix="wiz_design_"))
        try:
            draft = tmp / "draft"
            try:
                bp.write_pack(copy.deepcopy(blueprint), draft)
                load_pack(draft, validate=True)
                return
            except PackValidationError as exc:
                pruned = _prune_bad_routing_examples(blueprint, str(exc))
                if pruned is None:
                    raise DesignError(f"designed pack failed validation: {exc}") from exc
                blueprint.clear()
                blueprint.update(pruned)
                shutil.rmtree(draft, ignore_errors=True)
                bp.write_pack(copy.deepcopy(blueprint), draft)
                try:
                    load_pack(draft, validate=True)
                except Exception as retry_exc:
                    raise DesignError(
                        f"designed pack failed validation: {retry_exc}"
                    ) from retry_exc
            except Exception as exc:
                raise DesignError(f"designed pack failed validation: {exc}") from exc
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


def _prune_bad_routing_examples(
    blueprint: dict[str, Any], error_text: str
) -> dict[str, Any] | None:
    """If every error is a routing.examples[i] miss, drop those examples."""
    import re

    idxs = {int(m) for m in re.findall(r"routing\.examples\[(\d+)\]", error_text)}
    if not idxs:
        return None
    # Reject if the message also carries non-example failures.
    other = [
        line.strip()
        for line in error_text.replace(";", "\n").splitlines()
        if line.strip() and "routing.examples[" not in line
    ]
    if other:
        return None
    examples = list(blueprint.get("examples") or [])
    if not examples:
        return None
    kept = [ex for i, ex in enumerate(examples) if i not in idxs]
    if not kept:
        return None
    out = copy.deepcopy(blueprint)
    out["examples"] = kept
    return out


__all__ = ["DesignError", "LLMBlueprintDesigner"]
