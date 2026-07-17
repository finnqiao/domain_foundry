"""Injectable clock — evals and contract tests must never read wall time."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime

_Clock = Callable[[], datetime]


def _wall_clock() -> datetime:
    return datetime.now(UTC)


_clock: _Clock = _wall_clock


def set_clock(fn: _Clock | None) -> None:
    """Install a clock provider. Pass None to restore wall clock."""
    global _clock
    _clock = fn if fn is not None else _wall_clock


def now() -> datetime:
    return _clock()


def now_iso() -> str:
    dt = now()
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC).isoformat().replace("+00:00", "Z")


def today_utc() -> str:
    return now().astimezone(UTC).strftime("%Y-%m-%d")
