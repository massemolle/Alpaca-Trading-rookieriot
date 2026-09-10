"""Long-leg construction fixes (2026-09-09 nightly finding, re-landed
2026-09-10 after a false-positive gate revert — the session's diff passed
128/129 tests; the one failure was an env-coupled blackout-date test).

Two live bugs pinned:
- GLD chain-top: the closest-anywhere long snap landed ON the short strike
  when the chain ran out above it -> same-strike non-spread, "non-positive
  credit (0.00)" every cycle. Long snap must consider only strikes strictly
  further OTM; a chain-edge short is excluded before quoting.
- TLT/XLF fall-through: only the single delta-best short was ever tried, so
  one junk long-leg quote lost the whole ticker. Selection now walks the
  liquid shorts in delta order and takes the first with a tradeable long.
"""
from __future__ import annotations

import pytest

from spread_builder import build_spread
from tests.test_spread_builder_otm import ChainMCP, _chain


@pytest.mark.asyncio
async def test_chain_top_short_never_pairs_with_itself():
    # Spot 100, bear call. 110 is the top of the chain: pre-fix its long leg
    # snapped back to 110 itself (same-strike, credit 0). Now 105 must be
    # chosen as the short with 110 as its long — a real spread.
    contracts, snaps = _chain("TSTB", "call", {
        105.0: (1.00, 1.10),
        110.0: (0.45, 0.55),
    })
    plan = await build_spread(ChainMCP(contracts, snaps), "TSTB", "short",
                              spot_price=100.0, realized_vol=0.30)
    assert plan is not None
    assert plan.short_strike == 105.0 and plan.long_strike == 110.0
    assert plan.long_strike != plan.short_strike


@pytest.mark.asyncio
async def test_bull_put_chain_bottom_mirror():
    # Spot 100, bull put; 90 is the bottom of the chain — same shape mirrored.
    contracts, snaps = _chain("TSTC", "put", {
        95.0: (1.00, 1.10),
        90.0: (0.45, 0.55),
    })
    plan = await build_spread(ChainMCP(contracts, snaps), "TSTC", "long",
                              spot_price=100.0, realized_vol=0.30)
    assert plan is not None
    assert plan.short_strike == 95.0 and plan.long_strike == 90.0


@pytest.mark.asyncio
async def test_single_strike_chain_builds_nothing():
    # Only one OTM strike exists: no further-OTM long is possible at all.
    contracts, snaps = _chain("TSTD", "call", {110.0: (0.9, 1.1)})
    plan = await build_spread(ChainMCP(contracts, snaps), "TSTD", "short",
                              spot_price=100.0, realized_vol=0.30)
    assert plan is None


@pytest.mark.asyncio
async def test_junk_long_leg_falls_through_to_next_short():
    # Delta-best short is 105, but its long (110) quotes untradeably wide —
    # which also disqualifies 110 as a short. Pre-fix: whole ticker died.
    # Now the walk falls through to the 115/120 spread instead.
    contracts, snaps = _chain("TSTE", "call", {
        105.0: (1.20, 1.30),
        110.0: None,          # junk quote -> kills 105's long AND 110 as short
        115.0: (0.32, 0.34),   # 6% spread — passes the 12% short gate
        120.0: (0.12, 0.13),   # 8% — passes the 25% long-leg gate
    })
    plan = await build_spread(ChainMCP(contracts, snaps), "TSTE", "short",
                              spot_price=100.0, realized_vol=0.30)
    assert plan is not None
    assert plan.short_strike == 115.0 and plan.long_strike == 120.0


@pytest.mark.asyncio
async def test_all_long_legs_junk_builds_nothing():
    # Every possible long leg is untradeable: exhaustion path, no plan.
    contracts, snaps = _chain("TSTF", "call", {
        105.0: (1.20, 1.30),
        110.0: None,
        115.0: None,
    })
    plan = await build_spread(ChainMCP(contracts, snaps), "TSTF", "short",
                              spot_price=100.0, realized_vol=0.30)
    assert plan is None
