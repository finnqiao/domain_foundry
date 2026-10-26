"""Offline adversarial checks: no provider credentials or network required."""
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
from pathlib import Path

import pytest

from domain_foundry_core.ledger.migrate import ensure_migrated
from domain_foundry_core.routing.cost import CostGuard, CostGuardConfig
from domain_foundry_core.security.store import connect_rw


def _reserve(path: str) -> str | None:
    return CostGuard(Path(path), CostGuardConfig(0.1, {})).reserve(0.06, tier="sota")


@pytest.fixture
def guard(tmp_path):
    path = tmp_path / 'ledger.sqlite'
    ensure_migrated(path, 'ledger')
    return CostGuard(path, CostGuardConfig(0.1, {'sota': 0.08}))


@pytest.mark.parametrize('executor', [ThreadPoolExecutor, ProcessPoolExecutor])
def test_parallel_admission_cannot_oversubscribe(guard, executor):
    with executor(max_workers=8) as pool:
        results = list(pool.map(_reserve, [str(guard.ledger_db)] * 24))
    assert sum(value is not None for value in results) == 1
    assert guard.spent_today() == pytest.approx(0.06)


def test_tier_and_daily_capacity(guard):
    assert guard.reserve(0.06, tier='sota')
    assert guard.reserve(0.03, tier='sota') is None
    assert guard.reserve(0.03, tier='routine')
    assert guard.reserve(0.02, tier='routine') is None


def test_settlement_once_and_exact_budget(guard):
    hold = guard.reserve(0.08, tier='sota')
    args = dict(provider='offline', model='fixture', input_tokens=5, output_tokens=2, cost_usd=0.04)
    assert guard.settle(hold, **args)
    assert not guard.settle(hold, **args)
    assert not guard.release_unsent(hold)
    assert guard.spent_today() == pytest.approx(0.04)
    assert guard.reserve(0.04, tier='sota')
    assert guard.reserve(0.001, tier='sota') is None


def test_parallel_settlement_exactly_once(guard):
    hold = guard.reserve(0.05)
    def settle(_):
        return guard.settle(hold, provider='offline', model=None, input_tokens=1, output_tokens=1, cost_usd=0.02)
    with ThreadPoolExecutor(max_workers=8) as pool:
        assert sum(pool.map(settle, range(24))) == 1
    assert guard.spent_today() == pytest.approx(0.02)


def test_unknown_outcome_persists_across_instances(guard):
    assert guard.reserve(0.08, tier='sota')
    other = CostGuard(guard.ledger_db, guard.config)
    assert other.reserve(0.01, tier='sota') is None
    assert not other.allow_llm(tier='sota')


def test_only_explicit_unsent_release_restores_capacity(guard):
    hold = guard.reserve(0.08, tier='sota')
    assert guard.release_unsent(hold)
    assert not guard.release_unsent(hold)
    assert guard.reserve(0.08, tier='sota')


def test_underestimated_cost_is_not_hidden(guard):
    hold = guard.reserve(0.01)
    assert guard.settle(hold, provider='offline', model=None, input_tokens=1, output_tokens=1, cost_usd=0.2)
    assert guard.spent_today() == pytest.approx(0.2)
    assert guard.reserve(0.001) is None


@pytest.mark.parametrize('value', [float('nan'), float('inf'), -1])
def test_invalid_configuration_and_accounting_fail_closed(guard, value):
    with pytest.raises(ValueError):
        CostGuardConfig(value)
    with pytest.raises(ValueError):
        guard.reserve(value)
    with pytest.raises(ValueError):
        guard.record(provider='offline', model=None, input_tokens=0, output_tokens=0, cost_usd=value)


def test_storage_missing_or_old_schema_never_grants_capacity(tmp_path):
    missing = CostGuard(tmp_path / 'missing.sqlite')
    assert not missing.allow_llm()
    assert missing.reserve(0.01) is None
    path = tmp_path / 'old.sqlite'
    conn = connect_rw(path)
    conn.execute('CREATE TABLE cost_ledger(day TEXT, cost_usd REAL, tier TEXT)')
    conn.close()
    old = CostGuard(path)
    assert not old.allow_llm()
    assert old.reserve(0.01) is None


def test_failed_settlement_retains_hold(guard):
    hold = guard.reserve(0.08, tier='sota')
    with pytest.raises(ValueError):
        guard.settle(hold, provider='offline', model=None, input_tokens=1, output_tokens=1, cost_usd=float('nan'))
    assert guard.reserve(0.01, tier='sota') is None


def test_midnight_restart_and_tighter_tier_cannot_drop_ambiguous_holds(guard, monkeypatch):
    from domain_foundry_core.routing import cost
    monkeypatch.setattr(cost, 'today_utc', lambda: '2026-10-25')
    assert guard.reserve(0.07, tier='sota')
    monkeypatch.setattr(cost, 'today_utc', lambda: '2026-10-26')
    restarted = CostGuard(guard.ledger_db, CostGuardConfig(0.1, {'sota': 0.05}))
    assert restarted.spent_today() == pytest.approx(0.07)
    assert restarted.spent_today(tier='sota') == pytest.approx(0.07)
    assert not restarted.allow_llm(tier='sota')
    assert restarted.reserve(0.01, tier='sota') is None
    assert restarted.reserve(0.04, tier='routine') is None


def test_unattributed_old_hold_consumes_each_tier(guard, monkeypatch):
    from domain_foundry_core.routing import cost
    monkeypatch.setattr(cost, 'today_utc', lambda: '2026-10-25')
    assert guard.reserve(0.07)
    monkeypatch.setattr(cost, 'today_utc', lambda: '2026-10-26')
    assert guard.reserve(0.02, tier='sota') is None
    assert guard.spent_today(tier='sota') == pytest.approx(0.07)


def test_quote_overrun_latches_across_midnight_and_budget_increase(guard, monkeypatch):
    from domain_foundry_core.routing import cost
    hold = guard.reserve(0.01)
    guard.settle(hold, provider='offline', model=None, input_tokens=1, output_tokens=1, cost_usd=0.02)
    monkeypatch.setattr(cost, 'today_utc', lambda: '2099-01-01')
    restarted = CostGuard(guard.ledger_db, CostGuardConfig(100, {}))
    assert not restarted.allow_llm()
    assert restarted.reserve(0.001) is None
    assert not restarted.release_unsent(hold)


def test_corrupt_database_denies_calls(tmp_path):
    path = tmp_path / 'broken.sqlite'
    path.write_bytes(b'not a database')
    broken = CostGuard(path)
    assert not broken.allow_llm()
    assert broken.reserve(0.01) is None


def test_unknown_tier_and_mutated_invalid_cap_cannot_bypass(guard):
    assert not guard.allow_llm(tier='misspelled-sota')
    assert guard.reserve(0.01, tier='misspelled-sota') is None
    guard.config.daily_usd_cap = float('nan')
    assert not guard.allow_llm()
    assert guard.reserve(0.01) is None


@pytest.mark.parametrize('bad', [-1.0, 'unparseable', float('inf')])
def test_individual_corrupt_ledger_rows_cannot_be_coerced_or_offset(guard, bad):
    from domain_foundry_core.clock import today_utc
    conn = connect_rw(guard.ledger_db)
    conn.execute("INSERT INTO cost_ledger(day, provider, cost_usd, created_at) VALUES (?, 'offline', ?, 'fixture')", (today_utc(), bad))
    conn.commit()
    conn.close()
    assert not guard.allow_llm()
    assert guard.reserve(0.01) is None
