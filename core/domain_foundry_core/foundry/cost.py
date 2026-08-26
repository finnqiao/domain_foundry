"""Metering for the Foundry pipeline's sota calls (ADR-010).

A propose plus a complete is six sota calls. Until this existed they were
recorded as per-stage token receipts inside the spec and written *nowhere else*,
so the daily cost guard that exists to bound spend could not see them: a caller
could run the expensive path all day and ``spent_today()`` would report zero.

The meter is a small collaborator rather than a hard dependency of the pipeline,
so the pipeline itself keeps no storage imports and stays testable with a stub.
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from domain_foundry_core.llm.pricing import estimate_cost_usd
from domain_foundry_core.paths import Workspace
from domain_foundry_core.routing.cost import CostGuard

# The ledger tier label every Foundry row is written under. Distinct from
# ``sota`` on purpose: these calls are a create-time capital cost, not part of
# the per-capture routine/sota split, and an operator wants to see them apart.
FOUNDRY_COST_TIER = "foundry"


class CostMeter(Protocol):
    """What the pipeline needs from a ledger. Structural, so stubs are trivial."""

    def allow(self) -> bool:
        """False once the daily cap is reached; the run stops before the call."""
        ...

    def record(
        self,
        *,
        stage: str,
        provider: str | None,
        model: str | None,
        input_tokens: int,
        output_tokens: int,
    ) -> None: ...


class LedgerCostMeter:
    """Writes ``cost_ledger`` rows under the ``foundry`` tier."""

    def __init__(self, guard: CostGuard, *, spec_id: str | None = None) -> None:
        self.guard = guard
        self.spec_id = spec_id
        self.spent_usd = 0.0
        self.rows = 0

    @classmethod
    def for_home(cls, home: Path | None = None, *, spec_id: str | None = None) -> LedgerCostMeter:
        workspace = Workspace(home)
        workspace.ensure_layout()
        return cls(CostGuard(workspace.ledger_db), spec_id=spec_id)

    def allow(self) -> bool:
        return self.guard.allow_llm(tier=FOUNDRY_COST_TIER)

    def record(
        self,
        *,
        stage: str,
        provider: str | None,
        model: str | None,
        input_tokens: int,
        output_tokens: int,
    ) -> None:
        cost = estimate_cost_usd(
            model=model, input_tokens=input_tokens, output_tokens=output_tokens
        )
        entry = f"foundry:{self.spec_id}:{stage}" if self.spec_id else f"foundry:{stage}"
        self.guard.record(
            provider=provider or "unknown",
            model=model,
            input_tokens=int(input_tokens or 0),
            output_tokens=int(output_tokens or 0),
            cost_usd=cost,
            entry_id=entry,
            tier=FOUNDRY_COST_TIER,
        )
        self.spent_usd += cost
        self.rows += 1


__all__ = ["FOUNDRY_COST_TIER", "CostMeter", "LedgerCostMeter"]
