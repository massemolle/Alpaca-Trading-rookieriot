"""build_spread must see the whole chain, not the first page of it.

Live incident (2026-09-08, cycles 126-135): `get_option_contracts` was called
with `limit: 100` and the `next_page_token` cursor was never followed. On
SPY's dense 09-18 expiration the first 100 puts by strike ran out ~150 points
below spot, so delta targeting only ever saw deep-OTM strikes and emitted a
degenerate $1-credit / $499-max-loss spread at the page boundary (612/607 vs
spot 767) every single cycle — while GLD/XLF/TLT, whose dense chains never
reached ATM inside one page, produced "no viable spread plan" all day.

The MCP server's acceptance of `page_token` / larger `limit` values is not
independently verified (REST-verified only, see lab_real_prices.py), so both
are guarded: any rejection degrades to exactly the legacy single-page fetch,
never to a lost ticker.
"""
from __future__ import annotations

import pytest

import spread_builder
from spread_builder import build_spread
from tests.conftest import snapshot
from tests.test_spread_builder_otm import ChainMCP, _chain, _contract, _expiration


@pytest.fixture(autouse=True)
def _clear_contract_cache():
    spread_builder._contract_cache.clear()
    yield
    spread_builder._contract_cache.clear()


class PagingChainMCP(ChainMCP):
    """Serves the canned chain in pages, like the real dense-chain endpoint."""

    def __init__(self, contracts, snapshots, page_size=100,
                 reject_page_token=False, max_accepted_limit=None):
        super().__init__(contracts, snapshots)
        self.page_size = page_size
        self.reject_page_token = reject_page_token
        self.max_accepted_limit = max_accepted_limit

    async def call(self, tool: str, arguments: dict):
        if tool != "get_option_contracts":
            return await super().call(tool, arguments)
        self.calls.append((tool, arguments))
        if self.max_accepted_limit is not None and arguments["limit"] > self.max_accepted_limit:
            raise RuntimeError("Alpaca MCP tool 'get_option_contracts' failed: invalid limit")
        if "page_token" in arguments:
            if self.reject_page_token:
                raise RuntimeError(
                    "Alpaca MCP tool 'get_option_contracts' failed: unexpected keyword 'page_token'"
                )
            start = int(arguments["page_token"])
        else:
            start = 0
        page = self.contracts[start : start + self.page_size]
        next_start = start + self.page_size
        token = str(next_start) if next_start < len(self.contracts) else None
        return {"data": {"option_contracts": page, "next_page_token": token}}


def _dense_truncated_chain():
    """The SPY shape: page one is deep-OTM puts only, ATM lives on page two.

    Spot 767, realized vol ~8% — the 0.13-delta short put belongs near 755.
    Strikes 400-520 (page one) quote wide/near-zero like the real indicative
    feed; 700-780 (page two) quote tight and tradeable.
    """
    exp = _expiration()
    contracts, snaps = [], {}
    for strike in range(400, 521):  # 121 deep-OTM strikes: >1 page of 100
        c = _contract("TSTP", "put", float(strike), exp)
        contracts.append(c)
        snaps[c["symbol"]] = snapshot(0.0, 0.01)  # zero-bid junk quote
    for strike in range(700, 781, 5):
        c = _contract("TSTP", "put", float(strike), exp)
        contracts.append(c)
        mid = (strike - 660) * 0.05  # put value grows with strike: 700→$2, 780→$6
        snaps[c["symbol"]] = snapshot(mid - 0.1, mid + 0.1)
    return contracts, snaps


@pytest.mark.asyncio
async def test_dense_chain_paginates_past_deep_otm_first_page():
    contracts, snaps = _dense_truncated_chain()
    mcp = PagingChainMCP(contracts, snaps, page_size=100)
    plan = await build_spread(mcp, "TSTP", "long", spot_price=767.0, realized_vol=0.08)
    assert plan is not None
    # Pre-fix this landed at the page-one boundary (~520 here, 612 live);
    # with the full chain the short leg must come from the tradeable
    # near-ATM band on page two.
    assert plan.short_strike >= 700.0
    assert plan.long_strike < plan.short_strike
    assert plan.credit_estimate > 0
    contract_calls = [a for t, a in mcp.calls if t == "get_option_contracts"]
    assert any("page_token" in a for a in contract_calls)


@pytest.mark.asyncio
async def test_page_token_rejection_degrades_to_first_page():
    # First page alone holds a buildable near-ATM chain; the cursor param
    # being rejected by the server must not lose the ticker.
    contracts, snaps = _chain("TSTQ", "put", {
        105.0: (5.4, 5.6),
        95.0: (1.0, 1.1),
        90.0: (0.40, 0.45),
        85.0: (0.15, 0.165),
    })
    mcp = PagingChainMCP(contracts, snaps, page_size=3, reject_page_token=True)
    plan = await build_spread(mcp, "TSTQ", "long", spot_price=100.0, realized_vol=0.30)
    assert plan is not None
    assert plan.short_strike < 100.0


@pytest.mark.asyncio
async def test_limit_rejection_retries_exact_legacy_page_size():
    contracts, snaps = _chain("TSTR", "put", {
        105.0: (5.4, 5.6),
        95.0: (1.0, 1.1),
        90.0: (0.40, 0.45),
        85.0: (0.15, 0.165),
    })
    mcp = PagingChainMCP(contracts, snaps, page_size=100, max_accepted_limit=100)
    plan = await build_spread(mcp, "TSTR", "long", spot_price=100.0, realized_vol=0.30)
    assert plan is not None
    contract_calls = [a for t, a in mcp.calls if t == "get_option_contracts"]
    assert contract_calls[0]["limit"] == spread_builder.CONTRACTS_PAGE_LIMIT
    assert contract_calls[1]["limit"] == 100


@pytest.mark.asyncio
async def test_snapshot_request_stays_bounded_on_full_chains():
    # A fully-paginated dense expiration must not turn into a 300-symbol
    # snapshot request: only the delta shortlist and its long legs get quoted.
    contracts, snaps = _dense_truncated_chain()
    mcp = PagingChainMCP(contracts, snaps, page_size=100)
    plan = await build_spread(mcp, "TSTP", "long", spot_price=767.0, realized_vol=0.08)
    assert plan is not None
    snap_calls = [a for t, a in mcp.calls if t == "get_option_snapshot"]
    assert snap_calls, "expected a snapshot request"
    for args in snap_calls:
        n_symbols = len(args["symbols"].split(","))
        assert n_symbols <= 2 * spread_builder.SHORT_CANDIDATE_COUNT


@pytest.mark.asyncio
async def test_runaway_cursor_stops_at_page_cap():
    contracts, snaps = _dense_truncated_chain()
    mcp = PagingChainMCP(contracts, snaps, page_size=1)  # 137 pages if unbounded
    await build_spread(mcp, "TSTP", "long", spot_price=767.0, realized_vol=0.08)
    contract_calls = [a for t, a in mcp.calls if t == "get_option_contracts"]
    assert len(contract_calls) == spread_builder.MAX_CONTRACT_PAGES
