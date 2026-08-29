"""Shared fakes for offline tests — no network, no real Alpaca/Supabase."""
from __future__ import annotations

import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from spread_builder import SpreadPlan  # noqa: E402


def make_plan(**overrides) -> SpreadPlan:
    defaults = dict(
        underlying="SPY",
        direction="bull_put",
        expiration=date.today() + timedelta(days=14),
        short_strike=640.0,
        long_strike=635.0,
        short_symbol="SPY260911P00640000",
        long_symbol="SPY260911P00635000",
        credit_estimate=150.0,
        max_loss=350.0,
    )
    defaults.update(overrides)
    return SpreadPlan(**defaults)


def snapshot(bid: float, ask: float, age_minutes: float = 1.0) -> dict:
    ts = datetime.now(timezone.utc) - timedelta(minutes=age_minutes)
    return {"latestQuote": {"bp": bid, "ap": ask, "t": ts.isoformat().replace("+00:00", "Z")}}


class FakeMCP:
    """Answers get_option_snapshot with canned per-symbol snapshots and
    records every call so tests can assert what was (not) requested."""

    def __init__(self, snapshots: dict[str, dict] | None = None):
        self.snapshots = snapshots or {}
        self.calls: list[tuple[str, dict]] = []

    async def call(self, tool: str, arguments: dict):
        self.calls.append((tool, arguments))
        if tool == "get_option_snapshot":
            wanted = arguments.get("symbols", "").split(",")
            return {"data": {"snapshots": {s: self.snapshots[s] for s in wanted if s in self.snapshots}}}
        raise AssertionError(f"unexpected MCP tool call in test: {tool}")


class FakeClient:
    def __init__(self, equity=100_000.0, last_equity=100_000.0, buying_power=200_000.0):
        self.account = {
            "equity": equity,
            "last_equity": last_equity,
            "cash": equity,
            "buying_power": buying_power,
        }

    def get_account(self) -> dict:
        return dict(self.account)


@pytest.fixture
def fake_db(monkeypatch):
    """Patches pretrade_gate's db binding; returns the mutable open-spreads list."""
    import pretrade_gate

    open_spreads: list[dict] = []

    class _DB:
        @staticmethod
        def get_open_spreads():
            return list(open_spreads)

    monkeypatch.setattr(pretrade_gate, "db", _DB)
    return open_spreads


@pytest.fixture
def capped_contracts(monkeypatch):
    """Allow multi-contract sizing in tests (production default is 1)."""
    import dataclasses
    import pretrade_gate

    risk = dataclasses.replace(pretrade_gate.config.risk, max_contracts_per_spread=10)
    cfg = dataclasses.replace(pretrade_gate.config, risk=risk)
    monkeypatch.setattr(pretrade_gate, "config", cfg)
    return cfg