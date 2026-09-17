"""The entry limit must reach Alpaca as a NEGATIVE mleg limit_price.

Alpaca's multi-leg limit_price is signed cost basis (alpaca-py
LimitOrderRequest docstring: "a positive value indicates a debit ... while
a negative value signifies a credit") — the same convention as the
top-level filled_avg_price pinned 2026-08-30 in test_fill_confirmation_sign.
open_spread previously submitted the credit floor as a POSITIVE number,
i.e. a debit-side bound that any credit fill satisfies at any price: on
2026-09-17 GLD submitted limit '0.48' and filled at 0.31/share, XLK '1.0'
filled at 0.88, QQQ '0.96' at 0.93 (state/bot.log) — three fills below
their own "floor", which a binding limit makes impossible. Every credit
open to date was effectively an unbounded marketable order, so the
anchored entry floor (2026-09-11, test_entry_fill_economics) never reached
the broker, and stops/profit targets (2x / 0.5x of the FILL) were anchored
to the degraded fills.

These tests pin the sign at the API boundary in both directions: opens
negative (credit received), closes positive (debit paid) — and that the
project-internal convention (credits positive everywhere else) is intact.
"""
from __future__ import annotations

import pytest

import bot
from executor_mcp import close_spread, limit_credit_price, open_spread
from tests.conftest import FakeMCP, make_plan


class _RecordingMCP(FakeMCP):
    """Extends the shared FakeMCP to also answer place_option_order."""

    def __init__(self, place_order_response: dict):
        super().__init__()
        self._place_order_response = place_order_response

    async def call(self, tool: str, arguments: dict):
        self.calls.append((tool, arguments))
        if tool == "place_option_order":
            return self._place_order_response
        return await super().call(tool, arguments)

    def order_payload(self) -> dict:
        payloads = [args for tool, args in self.calls if tool == "place_option_order"]
        assert payloads, "place_option_order was never called"
        return payloads[-1]


def _filled_response() -> dict:
    return {"data": {"id": "o1", "status": "filled", "legs": [
        {"symbol": "SPY260911P00640000", "side": "sell", "filled_avg_price": "0.93"},
        {"symbol": "SPY260911P00635000", "side": "buy", "filled_avg_price": "0.59"},
    ]}}


@pytest.mark.asyncio
async def test_open_submits_negative_signed_credit_limit():
    mcp = _RecordingMCP(_filled_response())

    await open_spread(mcp, make_plan(), contracts=1, limit_credit=0.48)

    payload = mcp.order_payload()
    assert payload["order_class"] == "mleg"
    assert payload["type"] == "limit"
    assert float(payload["limit_price"]) == pytest.approx(-0.48)


@pytest.mark.asyncio
async def test_open_default_limit_is_negative_too():
    """When no explicit limit is passed, the floor computed from the plan's
    own credit estimate must also be negated at the boundary."""
    mcp = _RecordingMCP(_filled_response())
    plan = make_plan(credit_estimate=150.0)

    await open_spread(mcp, plan, contracts=1)

    expected_floor = limit_credit_price(150.0)  # positive, project-internal
    assert expected_floor > 0
    assert float(mcp.order_payload()["limit_price"]) == pytest.approx(-expected_floor)


@pytest.mark.asyncio
async def test_close_keeps_positive_debit_limit():
    """Closing a credit spread PAYS a net debit — positive cost basis, so
    the close side must NOT be negated. The asymmetry is the convention."""
    mcp = _RecordingMCP({"data": {"id": "o1", "status": "filled", "legs": [
        {"symbol": "SPY260911P00640000", "side": "buy", "filled_avg_price": "2.00"},
        {"symbol": "SPY260911P00635000", "side": "sell", "filled_avg_price": "0.50"},
    ]}})

    await close_spread(
        mcp, "SPY260911P00640000", "SPY260911P00635000", contracts=1, limit_debit=1.5,
    )

    assert float(mcp.order_payload()["limit_price"]) == pytest.approx(1.5)


@pytest.mark.asyncio
async def test_todays_gld_shape_cannot_fill_below_the_floor_anymore():
    """Regression pin of the exact 2026-09-17 GLD 417/422 shape: judged
    credit $53, gate-fresh $45.5 → anchored floor 0.48/share, submitted as
    '0.48' and filled at 0.31 (cost basis −0.31). Under the signed limit a
    fill is admissible iff its cost basis <= limit_price; the real degraded
    fill must now violate that."""
    floor = bot._entry_limit_credit(53.0, 45.5)
    assert floor == limit_credit_price(53.0)  # anchor identity, env-robust

    mcp = _RecordingMCP(_filled_response())
    await open_spread(mcp, make_plan(), contracts=1, limit_credit=floor)

    submitted = float(mcp.order_payload()["limit_price"])
    assert submitted == pytest.approx(-floor)
    degraded_fill_cost_basis = -0.31  # what GLD actually filled at
    assert not degraded_fill_cost_basis <= submitted, (
        "the 0.31/share fill would still satisfy the submitted limit — "
        "the credit floor is not binding"
    )


@pytest.mark.asyncio
async def test_fill_extraction_unaffected_by_submission_sign():
    """The negation lives at the request boundary only: the recorded
    fill_credit still comes back POSITIVE from the per-leg extraction."""
    mcp = _RecordingMCP(_filled_response())

    order = await open_spread(mcp, make_plan(), contracts=1, limit_credit=0.48)

    assert order.fill_credit == pytest.approx(34.0)  # 0.93 − 0.59 per share
    assert float(mcp.order_payload()["limit_price"]) < 0
