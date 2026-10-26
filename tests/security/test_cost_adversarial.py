import sqlite3
from concurrent.futures import ThreadPoolExecutor

import pytest

from domain_foundry_core.clock import now_iso, today_utc
from domain_foundry_core.ledger.migrate import ensure_migrated
from domain_foundry_core.routing.cost import CostGuard, CostGuardConfig
from domain_foundry_core.security.store import connect_rw


@pytest.fixture
def guard(tmp_path):
    p = tmp_path / "review.sqlite"
    ensure_migrated(p, "ledger")
    return CostGuard(p, CostGuardConfig(0.1, {"sota": 0.08}))


def _insert(guard, cost):
    conn = connect_rw(guard.ledger_db)
    conn.execute(
        "INSERT INTO cost_ledger (day,provider,model,input_tokens,output_tokens,cost_usd,created_at,tier) VALUES (?, ?, ?, 1, 1, ?, ?, ?)",
        (today_utc(), "offline", "synthetic", cost, now_iso(), "sota"),
    )
    conn.commit()
    conn.close()


@pytest.mark.parametrize("cost", ["unparseable", -0.01])
def test_malformed_individual_ledger_cost_must_deny(guard, cost):
    # Prior schema has REAL affinity but no CHECK/STRICT numeric guarantee.
    _insert(guard, 0.06)
    _insert(guard, cost)
    assert guard.reserve(0.01, tier="sota") is None


def test_settlement_storage_failure_preserves_hold(guard):
    hold = guard.reserve(0.08, tier="sota")
    conn = connect_rw(guard.ledger_db)
    conn.execute(
        "CREATE TRIGGER review_failure BEFORE INSERT ON cost_ledger BEGIN SELECT RAISE(ABORT, 'synthetic persistence failure'); END"
    )
    conn.commit()
    conn.close()
    with pytest.raises(sqlite3.Error):
        guard.settle(
            hold,
            provider="offline",
            model="synthetic",
            input_tokens=1,
            output_tokens=1,
            cost_usd=0.02,
        )
    assert guard.spent_today() == pytest.approx(0.08)
    assert guard.reserve(0.01, tier="sota") is None


def test_release_settle_race_is_single_terminal_write(guard):
    hold = guard.reserve(0.05, tier="sota")

    def finish(i):
        if i % 2:
            return guard.release_unsent(hold)
        return guard.settle(
            hold,
            provider="offline",
            model="synthetic",
            input_tokens=1,
            output_tokens=1,
            cost_usd=0.02,
        )

    with ThreadPoolExecutor(max_workers=12) as pool:
        assert sum(pool.map(finish, range(48))) == 1
    assert guard.spent_today() in (0, 0.02)
