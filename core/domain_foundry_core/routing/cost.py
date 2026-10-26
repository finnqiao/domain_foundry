"""Daily LLM cost guard + cost_ledger writes (with per-tier budgets)."""

from __future__ import annotations

import math
import os
import sqlite3
import uuid
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
        value = float(raw)
        return value if math.isfinite(value) and value >= 0 else 0.0
    except ValueError:
        return 0.0


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

    def __post_init__(self) -> None:
        values = [self.daily_usd_cap, *self.tier_caps.values()]
        if any(not math.isfinite(value) or value < 0 for value in values):
            raise ValueError("Budget caps must be finite and non-negative")

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


def _storage_valid(conn: sqlite3.Connection) -> bool:
    # SQLite SUM silently coerces text to zero; negative rows can conceal spend.
    # Reject corrupt/legacy values individually rather than validating the sum.
    bad_cost = conn.execute(
        "SELECT 1 FROM cost_ledger WHERE typeof(cost_usd) NOT IN ('integer', 'real') "
        "OR cost_usd < 0 OR cost_usd > 1.7976931348623157e308 LIMIT 1"
    ).fetchone()
    bad_hold = conn.execute(
        "SELECT 1 FROM cost_reservation WHERE typeof(amount_usd) NOT IN ('integer', 'real') "
        "OR amount_usd <= 0 OR amount_usd > 1.7976931348623157e308 LIMIT 1"
    ).fetchone()
    return bad_cost is None and bad_hold is None


class CostGuard:
    def __init__(self, ledger_db: Path, config: CostGuardConfig | None = None) -> None:
        self.ledger_db = ledger_db
        self.config = config or CostGuardConfig.from_env()

    def spent_today(self, *, tier: str | None = None) -> float:
        day = today_utc()
        if not self.ledger_db.exists():
            return math.inf
        try:
            conn = connect_ro(self.ledger_db)
        except (sqlite3.Error, OSError):
            return math.inf
        try:
            if not _storage_valid(conn):
                return math.inf
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
            held = conn.execute(
                "SELECT COALESCE(SUM(amount_usd), 0) FROM cost_reservation "
                "WHERE status = 'held'" + (" AND (tier = ? OR tier IS NULL)" if tier else ""),
                (tier,) if tier else (),
            ).fetchone()[0]
            total = float(row["s"] if row else 0.0) + float(held)
            return total if math.isfinite(total) and total >= 0 else math.inf
        except sqlite3.Error:
            return math.inf
        finally:
            conn.close()

    def allow_llm(self, *, tier: str | None = None) -> bool:
        if tier not in {None, "routine", "sota", "foundry"}:
            return False
        try:
            self.config.__post_init__()
        except (ValueError, TypeError):
            return False
        try:
            conn = connect_ro(self.ledger_db)
            try:
                if conn.execute("SELECT 1 FROM cost_reservation WHERE status = 'overrun' LIMIT 1").fetchone():
                    return False
            finally:
                conn.close()
        except (sqlite3.Error, OSError):
            return False
        if self.spent_today() >= self.config.daily_usd_cap:
            return False
        if tier:
            cap = self.config.tier_caps.get(tier)
            if cap is not None and self.spent_today(tier=tier) >= cap:
                return False
        return True

    def reserve(self, amount_usd: float, *, tier: str | None = None) -> str | None:
        """Atomically reserve a caller-proven upper bound before external work.

        Returns None on unavailable capacity/storage. The caller MUST include
        all retries/output in the quote; this local ledger cannot constrain
        a stolen provider key or other workspaces. Never expire an ambiguous
        in-flight hold automatically: a timed-out request may still be billed.
        """
        if not math.isfinite(amount_usd) or amount_usd <= 0:
            raise ValueError("Reservation must be finite and positive")
        if tier not in {None, "routine", "sota", "foundry"}:
            return None
        try:
            self.config.__post_init__()
        except (ValueError, TypeError):
            return None
        if not self.ledger_db.exists():
            return None
        conn = None
        try:
            conn = connect_rw(self.ledger_db)
            conn.execute("BEGIN IMMEDIATE")
            if not _storage_valid(conn):
                return None
            if conn.execute("SELECT 1 FROM cost_reservation WHERE status = 'overrun' LIMIT 1").fetchone():
                return None
            day = today_utc()
            def total(for_tier: str | None = None) -> float:
                suffix = " AND tier = ?" if for_tier else ""
                params = (day, for_tier) if for_tier else (day,)
                spent = conn.execute(
                    "SELECT COALESCE(SUM(cost_usd), 0) FROM cost_ledger WHERE day = ?" + suffix,
                    params,
                ).fetchone()[0]
                held = conn.execute(
                    "SELECT COALESCE(SUM(amount_usd), 0) FROM cost_reservation "
                    "WHERE status = 'held'" + (" AND (tier = ? OR tier IS NULL)" if for_tier else ""),
                    (for_tier,) if for_tier else (),
                ).fetchone()[0]
                # Unattributed legacy rows conservatively consume every tier.
                legacy = 0.0
                if for_tier:
                    legacy = conn.execute(
                        "SELECT COALESCE(SUM(cost_usd), 0) FROM cost_ledger WHERE day = ? AND tier IS NULL",
                        (day,),
                    ).fetchone()[0]
                value = float(spent) + float(held) + float(legacy)
                return value if math.isfinite(value) and value >= 0 else math.inf
            if total() + amount_usd > self.config.daily_usd_cap:
                return None
            cap = self.config.tier_caps.get(tier) if tier else None
            if cap is not None and total(tier) + amount_usd > cap:
                return None
            reservation = uuid.uuid4().hex
            conn.execute(
                "INSERT INTO cost_reservation(id, day, tier, amount_usd, status, created_at) "
                "VALUES (?, ?, ?, ?, 'held', ?)",
                (reservation, day, tier, amount_usd, now_iso()),
            )
            conn.commit()
            return reservation
        except (sqlite3.Error, OSError):
            return None
        finally:
            if conn is not None:
                conn.close()

    def settle(
        self, reservation: str, *, provider: str, model: str | None,
        input_tokens: int, output_tokens: int, cost_usd: float,
        entry_id: str | None = None,
    ) -> bool:
        """Replace a hold with known billed cost atomically, exactly once.

        Record over-estimates AND under-estimates honestly, even over the cap.
        Missing/invalid usage must leave the hold in place, not charge zero.
        """
        if not math.isfinite(cost_usd) or cost_usd < 0:
            raise ValueError("Cost must be finite and non-negative")
        if input_tokens < 0 or output_tokens < 0:
            raise ValueError("Token counts must be non-negative")
        conn = connect_rw(self.ledger_db)
        try:
            conn.execute("BEGIN IMMEDIATE")
            hold = conn.execute("SELECT * FROM cost_reservation WHERE id = ?", (reservation,)).fetchone()
            if hold is None or hold["status"] != "held":
                return False
            conn.execute(
                "INSERT INTO cost_ledger(day, provider, model, input_tokens, output_tokens, "
                "cost_usd, entry_id, created_at, tier) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (hold["day"], provider, model, input_tokens, output_tokens, cost_usd,
                 entry_id, now_iso(), hold["tier"]),
            )
            status = "overrun" if cost_usd > hold["amount_usd"] else "settled"
            conn.execute("UPDATE cost_reservation SET status = ?, settled_at = ? WHERE id = ?",
                         (status, now_iso(), reservation))
            conn.commit()
            return True
        finally:
            conn.close()

    def release_unsent(self, reservation: str) -> bool:
        """Release ONLY a request known not to have been dispatched.

        A timeout, parse failure, or process crash is not proof of no charge.
        """
        conn = connect_rw(self.ledger_db)
        try:
            cursor = conn.execute(
                "UPDATE cost_reservation SET status = 'released', settled_at = ? "
                "WHERE id = ? AND status = 'held'", (now_iso(), reservation),
            )
            conn.commit()
            return cursor.rowcount == 1
        finally:
            conn.close()

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
        if not math.isfinite(cost_usd) or cost_usd < 0:
            raise ValueError("Cost must be finite and non-negative")
        if input_tokens < 0 or output_tokens < 0:
            raise ValueError("Token counts must be non-negative")
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
