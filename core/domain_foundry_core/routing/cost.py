"""Daily LLM cost guard + cost_ledger writes (with per-tier budgets)."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from domain_foundry_core.clock import now_iso, today_utc
from domain_foundry_core.security.store import connect_ro, connect_rw

# Private Hermes stack uses $0.25/day; port that as the OSS default.
_DEFAULT_DAILY = 0.25
_DEFAULT_ROUTINE = 0.15
_DEFAULT_SOTA = 0.10


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return float(raw)
    except ValueError:
        return default


@dataclass
class CostGuardConfig:
    daily_usd_cap: float = _DEFAULT_DAILY
    # Per-tier budgets under the daily cap. None = no separate tier cap.
    tier_caps: dict[str, float] = field(
        default_factory=lambda: {
            "routine": _DEFAULT_ROUTINE,
            "sota": _DEFAULT_SOTA,
        }
    )

    @classmethod
    def from_env(cls, *, daily_usd_cap: float | None = None) -> CostGuardConfig:
        daily = (
            daily_usd_cap
            if daily_usd_cap is not None
            else _env_float("DOMAIN_FOUNDRY_DAILY_COST_CAP", _DEFAULT_DAILY)
        )
        return cls(
            daily_usd_cap=daily,
            tier_caps={
                "routine": _env_float(
                    "DOMAIN_FOUNDRY_ROUTINE_COST_CAP", _DEFAULT_ROUTINE
                ),
                "sota": _env_float("DOMAIN_FOUNDRY_SOTA_COST_CAP", _DEFAULT_SOTA),
            },
        )


class CostGuard:
    def __init__(self, ledger_db: Path, config: CostGuardConfig | None = None) -> None:
        self.ledger_db = ledger_db
        self.config = config or CostGuardConfig.from_env()

    def spent_today(self, *, tier: str | None = None) -> float:
        day = today_utc()
        if not self.ledger_db.exists():
            return 0.0
        conn = connect_ro(self.ledger_db)
        try:
            if tier:
                # Prefer explicit tier column; fall back to model-inferred rows
                # when tier was not recorded (pre-migration writes).
                row = conn.execute(
                    """
                    SELECT COALESCE(SUM(cost_usd), 0) AS s FROM cost_ledger
                    WHERE day = ? AND (
                        tier = ?
                        OR (tier IS NULL AND (
                            (? = 'routine' AND (
                                model LIKE 'deepseek%' OR model LIKE 'gpt-%'
                            ))
                            OR (? = 'sota' AND model LIKE 'claude%')
                        ))
                    )
                    """,
                    (day, tier, tier, tier),
                ).fetchone()
            else:
                row = conn.execute(
                    "SELECT COALESCE(SUM(cost_usd), 0) AS s FROM cost_ledger WHERE day = ?",
                    (day,),
                ).fetchone()
            return float(row["s"] if row else 0.0)
        except Exception:
            return 0.0
        finally:
            conn.close()

    def allow_llm(self, *, tier: str | None = None) -> bool:
        if self.spent_today() >= self.config.daily_usd_cap:
            return False
        if tier:
            cap = self.config.tier_caps.get(tier)
            if cap is not None and self.spent_today(tier=tier) >= cap:
                return False
        return True

    def record(
        self,
        *,
        provider: str,
        model: str | None,
        input_tokens: int,
        output_tokens: int,
        cost_usd: float,
        entry_id: str | None = None,
        tier: str | None = None,
    ) -> None:
        conn = connect_rw(self.ledger_db)
        try:
            # Detect whether the tier column exists (pre/post ledger_003).
            cols = {
                r[1]
                for r in conn.execute("PRAGMA table_info(cost_ledger)").fetchall()
            }
            if "tier" in cols:
                conn.execute(
                    """
                    INSERT INTO cost_ledger (
                        day, provider, model, input_tokens, output_tokens,
                        cost_usd, entry_id, created_at, tier
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                        tier,
                    ),
                )
            else:
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
