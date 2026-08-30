"""Tests for quantity-aware sizing, mechanical selector, reconciler, monitor marks."""
from __future__ import annotations

from sizing import optimal_contracts
from selector import mechanical_score, shadow_select, aggregate_max_loss
from reconciler import reconcile, _option_symbols_from_positions


def test_optimal_contracts_respects_budget():
    # 2% of 100k = 2000; max_loss 350 → 5 contracts
    assert optimal_contracts(100_000, 350, 0.02) == 5
    assert optimal_contracts(100_000, 350, 0.02, max_contracts=1) == 1
    assert optimal_contracts(100_000, 3000, 0.02) == 0  # even 1 exceeds


def test_mechanical_score_and_select():
    cands = [
        {"ticker": "A", "strength": 1.0, "credit_estimate": 100, "max_loss": 400},
        {"ticker": "B", "strength": 0.5, "credit_estimate": 200, "max_loss": 300},
        {"ticker": "C", "strength": 0.9, "credit_estimate": 50, "max_loss": 450},
    ]
    assert mechanical_score(cands[1]) > mechanical_score(cands[0])  # better RR
    picked = shadow_select(cands, remaining_budget=2)
    assert picked[0] == "B"
    assert len(picked) == 2


def test_shadow_select_uses_contracts_in_budget():
    cands = [
        {"ticker": "A", "strength": 1.0, "credit_estimate": 100, "max_loss": 200, "contracts": 3},
        {"ticker": "B", "strength": 0.5, "credit_estimate": 50, "max_loss": 100, "contracts": 1},
    ]
    # A uses 600 risk; budget 500 → skip A, take B
    picked = shadow_select(cands, remaining_budget=2, max_aggregate_loss=500)
    assert picked == ["B"]


def test_shadow_select_respects_aggregate_loss():
    cands = [
        {"ticker": "A", "strength": 1.0, "credit_estimate": 100, "max_loss": 500},
        {"ticker": "B", "strength": 0.9, "credit_estimate": 100, "max_loss": 500},
        {"ticker": "C", "strength": 0.8, "credit_estimate": 100, "max_loss": 100},
    ]
    # C scores highest (0.8 RR). Budget 550: C(100) then A(500) = 600 > 550 → skip A.
    # Only C fits after C is taken first.
    picked = shadow_select(cands, remaining_budget=2, max_aggregate_loss=550)
    assert picked == ["C"]
    # Larger budget fits C + A
    picked2 = shadow_select(cands, remaining_budget=2, max_aggregate_loss=650)
    assert picked2 == ["C", "A"]


def test_aggregate_max_loss_multiplies_contracts():
    cands = [{"ticker": "SPY", "max_loss": 350, "contracts": 3}]
    assert aggregate_max_loss(cands, ["SPY"]) == 1050


def test_option_symbol_heuristic():
    positions = [
        {"symbol": "SPY"},
        {"symbol": "SPY260911P00640000"},
        {"symbol": "AAPL"},
        {"symbol": "QQQ260918C00450000"},
    ]
    opts = _option_symbols_from_positions(positions)
    assert "SPY260911P00640000" in opts
    assert "QQQ260918C00450000" in opts
    assert "SPY" not in opts


def test_reconcile_detects_phantom(monkeypatch):
    import reconciler as rec

    class Client:
        def get_positions(self):
            return [{"symbol": "SPY"}]  # no option legs

        def get_orders(self, status="open"):
            return []

    class FakeDB:
        @staticmethod
        def get_open_spreads():
            return [{
                "underlying": "SPY",
                "short_symbol": "SPY260911P00640000",
                "long_symbol": "SPY260911P00635000",
            }]

        @staticmethod
        def get_spreads_by_status(status):
            return []

    monkeypatch.setattr(rec, "db", FakeDB)
    result = reconcile(Client())
    assert not result.ok
    assert "missing at broker" in result.reason


def test_reconcile_detects_leg_quantity_mismatch(monkeypatch):
    """2026-08-30: the symbol-only check above can't see a leg quietly
    filled at a different size than its own DB record -- found auditing
    the same pattern in a sibling project's copy of this reconciler."""
    import reconciler as rec

    class Client:
        def get_positions(self):
            return [
                {"symbol": "SPY260911P00640000", "side": "short", "qty": 5.0},  # DB says 2
                {"symbol": "SPY260911P00635000", "side": "long", "qty": 2.0},
            ]

        def get_orders(self, status="open"):
            return []

    class FakeDB:
        @staticmethod
        def get_open_spreads():
            return [{
                "id": 1, "underlying": "SPY",
                "short_symbol": "SPY260911P00640000",
                "long_symbol": "SPY260911P00635000",
                "contracts": 2,
            }]

        @staticmethod
        def get_spreads_by_status(status):
            return []

    monkeypatch.setattr(rec, "db", FakeDB)
    result = reconcile(Client())
    assert not result.ok
    assert "DB says 2 contract(s), broker says 5.0" in result.reason


def test_reconcile_detects_leg_side_mismatch(monkeypatch):
    """A short leg recorded at the broker as long (or vice versa) is a
    real capital-structure inconsistency, not just a quantity typo."""
    import reconciler as rec

    class Client:
        def get_positions(self):
            return [
                {"symbol": "SPY260911P00640000", "side": "long", "qty": 1.0},  # DB says short
                {"symbol": "SPY260911P00635000", "side": "long", "qty": 1.0},
            ]

        def get_orders(self, status="open"):
            return []

    class FakeDB:
        @staticmethod
        def get_open_spreads():
            return [{
                "id": 1, "underlying": "SPY",
                "short_symbol": "SPY260911P00640000",
                "long_symbol": "SPY260911P00635000",
                "contracts": 1,
            }]

        @staticmethod
        def get_spreads_by_status(status):
            return []

    monkeypatch.setattr(rec, "db", FakeDB)
    result = reconcile(Client())
    assert not result.ok
    assert "expected side 'short', broker says 'long'" in result.reason


def test_spread_monitor_mark_units():
    """Regression: mark must be dollars-per-contract (×100), matching credit."""
    from spread_monitor import SpreadMonitor

    mon = SpreadMonitor()
    mon._quotes = {
        "S": {"bid": 1.90, "ask": 2.10},
        "L": {"bid": 0.45, "ask": 0.55},
    }
    mark = mon._compute_mark("S", "L")
    # short mid 2.00 - long mid 0.50 = 1.50/share → 150/contract
    assert mark == 150.0


def test_limit_credit_price_applies_slippage():
    import executor_mcp
    # 150/contract → 1.50/share; 10% slip → 1.35
    assert executor_mcp.limit_credit_price(150.0, slippage_pct=0.10) == 1.35


def test_macro_blackout_windows(monkeypatch):
    from datetime import datetime, timezone
    import risk_gate

    inside = datetime(2026, 9, 4, 12, 30, tzinfo=timezone.utc)   # NFP release
    outside = datetime(2026, 9, 4, 16, 0, tzinfo=timezone.utc)
    hit, reason = risk_gate.in_macro_blackout(inside)
    assert hit and "blackout" in reason
    hit, _ = risk_gate.in_macro_blackout(outside)
    assert not hit
    # env override + malformed entries are skipped, not fatal
    monkeypatch.setenv("MACRO_BLACKOUTS", "garbage,2026-09-02T10:00/2026-09-02T11:00")
    hit, _ = risk_gate.in_macro_blackout(datetime(2026, 9, 2, 10, 30, tzinfo=timezone.utc))
    assert hit
