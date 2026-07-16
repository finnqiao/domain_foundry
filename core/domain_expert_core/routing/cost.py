"""Daily LLM cost guard + cost_ledger writes."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from domain_expert_core.clock import now_iso, today_utc
from domain_expert_core.security.store import connect_ro, connect_rw


@dataclass
class CostGuardConfig:
    daily_usd_cap: float = 2.0


class CostGuard:
    def __init__(self, ledger_db: Path, config: CostGuardConfig | None = None) -> None:
        self.ledger_db = ledger_db
        self.config = config or CostGuardConfig()

    def spent_today(self) -> float:
        day = today_utc()
        if not self.ledger_db.exists():
            return 0.0
        conn = connect_ro(self.ledger_db)
        try:
            row = conn.execute(
                "SELECT COALESCE(SUM(cost_usd), 0) AS s FROM cost_ledger WHERE day = ?",
                (day,),
            ).fetchone()
            return float(row["s"] if row else 0.0)
        finally:
            conn.close()

    def allow_llm(self) -> bool:
        return self.spent_today() < self.config.daily_usd_cap

    def record(
        self,
        *,
        provider: str,
        model: str | None,
        input_tokens: int,
        output_tokens: int,
        cost_usd: float,
        entry_id: str | None = None,
    ) -> None:
        conn = connect_rw(self.ledger_db)
        try:
            conn.execute(
                """
                INSERT INTO cost_ledger (
                    day, provider, model, input_tokens, output_tokens,
                    cost_usd, entry_id, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    today_utc(),
                    provider,
                    model,
                    input_tokens,
                    output_tokens,
                    cost_usd,
                    entry_id,
                    now_iso(),
                ),
            )
            conn.commit()
        finally:
            conn.close()
