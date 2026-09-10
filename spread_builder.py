"""Turns a (ticker, direction) signal from the vendored screening/signals
modules into a concrete credit vertical spread: an expiration, a short
strike near the target delta, and a long strike `spread_width_dollars`
further out-of-the-money.

Bull put spread on a 'long' signal (sell a put, buy a further-OTM put —
profits if the underlying stays flat or rises). Bear call spread on a
'short' signal (sell a call, buy a further-OTM call — profits if the
underlying stays flat or falls). Both are defined-risk: max loss is fixed
at (width - credit received) the moment the spread opens, which is exactly
what risk_gate.check_new_spread checks against.

REAL API SHAPES (verified against the live account 2026-08-26, replacing an
earlier version's guessed field names — see git history for what was wrong):
- `get_option_contracts` (NOT get_option_chain) is the structural chain
  listing: response is `{"data": {"option_contracts": [...], "next_page_token": ...}}`,
  each contract a dict with STRING-typed `strike_price`/`open_interest`
  (nullable), plus `symbol`, `expiration_date`, `type` ("call"/"put").
  Param name is `underlying_symbols` (plural, comma-separated string),
  unlike get_option_chain's `underlying_symbol` (singular) — a real,
  easy-to-miss inconsistency in Alpaca's own tool schemas.
  PAGINATION MATTERS (live incident 2026-09-08): a single `limit: 100` page
  of a dense chain (SPY's Friday expirations list strikes from ~half spot
  up) is exhausted ~150 points below the money — every strike the delta
  targeting then sees is deep OTM, and the "best" plan is a degenerate
  $1-credit spread at the page boundary (SPY 612/607 vs spot 767, cycles
  126-135). Dense chains the page never reaches ATM on (GLD/XLF/TLT)
  produced "no viable spread plan" every cycle instead. `page_token` is the
  REST-verified request param for the `next_page_token` cursor (see
  lab_real_prices.py); this MCP server version accepting it is NOT
  independently verified, so pagination failures degrade to the pages
  already fetched rather than erroring the ticker.
- `get_option_snapshot` response is `{"data": {"snapshots": {symbol: {...}}}}`
  — one level deeper than assumed originally — and each snapshot's quote is
  under camelCase `latestQuote: {bp, ap, bs, as, ...}` (bid/ask price/size),
  NOT `latest_quote.bid_price`/`ask_price`.
- NO GREEKS AVAILABLE on this account on any feed: `feed=opra` 403s with
  "OPRA agreement is not signed" (real-time OPRA data requires Alpaca's
  paid Algo Trader Plus subscription — confirmed via Alpaca's own forum,
  not just this account's error message), and `feed=indicative` (the free
  tier) returns a quote with no `greeks` key at all. Delta is computed
  in-process instead — see black_scholes.py's module docstring for why
  this is a reasonable proxy, not a hack.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from black_scholes import bs_delta
from config import config
from mcp_client import AlpacaMCP

logger = logging.getLogger(__name__)

_contract_cache: dict[tuple, list[dict]] = {}


@dataclass
class SpreadPlan:
    underlying: str
    direction: str  # 'bull_put' | 'bear_call'
    expiration: date
    short_strike: float
    long_strike: float
    short_symbol: str
    long_symbol: str
    credit_estimate: float
    max_loss: float


def _mid_from_snapshot(snap: dict) -> float | None:
    quote = snap.get("latestQuote")
    if not quote:
        return None
    bid, ask = quote.get("bp"), quote.get("ap")
    if bid is None or ask is None:
        return None
    return (float(bid) + float(ask)) / 2


LONG_LEG_MAX_SPREAD_PCT = 0.25

# How many nearest-to-target-delta OTM strikes get quoted per ticker. The
# chosen short is the liquid strike nearest the delta target, so anything
# past the ~20 nearest is only reachable when 20 closer strikes all failed
# liquidity — at which point the chain isn't tradeable anyway.
SHORT_CANDIDATE_COUNT = 20

# Expirations tried per ticker per cycle, nearest-first (2026-09-10 nightly:
# "nearest expiration THAT BUILDS"). One snapshot batch per attempt, and an
# attempt beyond the first happens only where the ticker previously died or
# built degenerate geometry, so the cap bounds API load, not capability. A
# chain whose three nearest expirations are all junk isn't tradeable anyway.
MAX_EXPIRATION_ATTEMPTS = 3

# A plan is "on-width" when its strike width is within this fraction of
# spread_width_dollars either way (grid snapping legitimately lands at e.g.
# $2.5 or $7.5 around a $5 target). Off-width plans — GLD 2026-09-09: the
# 09-21 chain topped out at 420, forcing width-1 spreads with ~$10-20 credit
# against ~$85 max loss — defer to a later expiration that builds on-width,
# and are kept only as a last resort so no ticker that builds today is lost.
WIDTH_TOLERANCE = 0.5


def _passes_liquidity(contract: dict, snap: dict, max_spread_override: float | None = None) -> bool:
    """Per-contract liquidity gate (2026-08-26 research pass) — equity-level
    liquidity (ScreeningFilters.min_avg_volume) is a poor proxy for options
    liquidity specifically. Checked on every leg individually, never
    averaged across a spread.

    `open_interest` enforced only when the API actually returns a value —
    verified directly against the live account that Alpaca's free/paper
    tier returns `open_interest: null` for real, currently-liquid contracts
    (confirmed on near-the-money SPY weekly puts with tight, tradeable
    spreads) — evidently a data-availability gap on this feed, not a
    genuine liquidity signal. Treating null as "reject" would silently
    reject nearly everything, including the most liquid instrument that
    exists; treating it as "unknown, don't penalize" and leaning on the
    bid-ask spread check — which the same live test showed DOES return
    real, usable values — is the honest choice here. The threshold still
    applies whenever a real number comes back.
    """
    oi_raw = contract.get("open_interest")
    if oi_raw is not None and int(oi_raw) < config.risk.min_open_interest:
        return False
    mid = _mid_from_snapshot(snap)
    if mid is None or mid <= 0:
        return False
    quote = snap["latestQuote"]
    bid, ask = float(quote["bp"]), float(quote["ap"])
    spread_pct = (ask - bid) / mid
    threshold = max_spread_override if max_spread_override is not None else config.risk.max_bid_ask_spread_pct
    return spread_pct <= threshold


# One page must reach past ATM on the densest chain we trade (SPY: ~380
# strikes below spot on a Friday expiration); 500 does with margin. The
# page cap only bounds a runaway cursor — 2 pages covers every live chain.
CONTRACTS_PAGE_LIMIT = 500
MAX_CONTRACT_PAGES = 8


async def _fetch_contracts(mcp: AlpacaMCP, ticker: str, option_type: str, min_exp: date, max_exp: date) -> list[dict]:
    cache_key = (ticker, option_type, min_exp.isoformat(), max_exp.isoformat())
    if cache_key in _contract_cache:
        return _contract_cache[cache_key]
    base_args = {
        "underlying_symbols": ticker,
        "type": option_type,
        "status": "active",
        "expiration_date_gte": min_exp.isoformat(),
        "expiration_date_lte": max_exp.isoformat(),
        "limit": CONTRACTS_PAGE_LIMIT,
    }
    try:
        result = await mcp.call("get_option_contracts", base_args)
    except Exception:
        # Never worse than the pre-pagination builder: if this MCP server
        # version rejects the larger page size, retry the exact legacy call.
        logger.warning(
            "%s: get_option_contracts rejected limit=%d, retrying legacy limit=100",
            ticker, CONTRACTS_PAGE_LIMIT,
        )
        result = await mcp.call("get_option_contracts", {**base_args, "limit": 100})
    data = (result or {}).get("data", {})
    contracts = list(data.get("option_contracts") or [])
    page_token = data.get("next_page_token")
    pages_fetched = 1
    while page_token and pages_fetched < MAX_CONTRACT_PAGES:
        try:
            result = await mcp.call(
                "get_option_contracts", {**base_args, "page_token": page_token}
            )
        except Exception:
            # `page_token` is REST-verified but not verified against this MCP
            # server version — a truncated chain still builds spreads (today's
            # behavior), a raised error would drop the ticker entirely.
            logger.warning(
                "%s: chain pagination failed after %d page(s); proceeding with "
                "%d contracts (chain may be truncated)",
                ticker, pages_fetched, len(contracts), exc_info=True,
            )
            break
        data = (result or {}).get("data", {})
        contracts.extend(data.get("option_contracts") or [])
        page_token = data.get("next_page_token")
        pages_fetched += 1
    if page_token:
        logger.warning(
            "%s: chain still paginated after %d pages (%d contracts) — dense "
            "chain or runaway cursor, proceeding with what we have",
            ticker, pages_fetched, len(contracts),
        )
    _contract_cache[cache_key] = contracts
    return contracts


async def _fetch_snapshots(mcp: AlpacaMCP, symbols: list[str]) -> dict[str, dict]:
    if not symbols:
        return {}
    result = await mcp.call(
        "get_option_snapshot",
        {"symbols": ",".join(symbols), "feed": "indicative"},
    )
    return (result or {}).get("data", {}).get("snapshots", {})


async def build_spread(
    mcp: AlpacaMCP,
    ticker: str,
    signal_direction: str,
    spot_price: float,
    realized_vol: float,
) -> SpreadPlan | None:
    """signal_direction is the vendored Signal's own 'long'/'short' field.
    `spot_price` is the underlying's current mid quote, `realized_vol` the
    annualized realized-vol estimate (see black_scholes.realized_vol_from_bars)
    used as the IV proxy for delta. Returns None (never a half-built spread)
    if the chain doesn't have a clean, liquid expiration/strike pair in the
    configured windows — a skipped cycle is always safer than a guessed one.

    Expirations inside the DTE window are tried nearest-first (most theta
    decay realized within the judged period): the first one that builds an
    on-width plan wins, an off-width plan is kept only as a last resort.
    """
    limits = config.risk
    today = datetime.now().date()
    min_exp = today + timedelta(days=limits.min_dte)
    max_exp = today + timedelta(days=limits.max_dte)

    is_bull_put = signal_direction == "long"
    option_type = "put" if is_bull_put else "call"

    contracts = await _fetch_contracts(mcp, ticker, option_type, min_exp, max_exp)
    if not contracts:
        logger.info("No %s contracts for %s in [%s, %s]", option_type, ticker, min_exp, max_exp)
        return None

    expirations = sorted({c["expiration_date"] for c in contracts if c.get("expiration_date")})
    off_width_plan: SpreadPlan | None = None
    for chosen_expiration in expirations[:MAX_EXPIRATION_ATTEMPTS]:
        exp_contracts = [c for c in contracts if c.get("expiration_date") == chosen_expiration]
        plan = await _build_for_expiration(
            mcp, ticker, chosen_expiration, exp_contracts,
            is_bull_put, option_type, spot_price, realized_vol, today,
        )
        if plan is None:
            continue
        width_ratio = abs(plan.short_strike - plan.long_strike) / limits.spread_width_dollars
        if abs(width_ratio - 1.0) <= WIDTH_TOLERANCE:
            return plan
        logger.info(
            "%s %s builds only at %.0f%% of the $%.0f target width",
            ticker, chosen_expiration, width_ratio * 100, limits.spread_width_dollars,
        )
        if off_width_plan is None:
            off_width_plan = plan
    if off_width_plan is not None:
        logger.info(
            "%s: no expiration in the window builds on-width — keeping off-width "
            "%s/%s @ %s as last resort",
            ticker, off_width_plan.short_strike, off_width_plan.long_strike,
            off_width_plan.expiration,
        )
    return off_width_plan


async def _build_for_expiration(
    mcp: AlpacaMCP,
    ticker: str,
    chosen_expiration: str,
    exp_contracts: list[dict],
    is_bull_put: bool,
    option_type: str,
    spot_price: float,
    realized_vol: float,
    today: date,
) -> SpreadPlan | None:
    """One expiration's worth of the original build: delta-target the short,
    snap the long, quote the shortlist, walk the liquid shorts. Unchanged
    semantics — build_spread only decides WHICH expirations get attempted.
    """
    limits = config.risk
    dte_days = (datetime.strptime(chosen_expiration, "%Y-%m-%d").date() - today).days

    def delta_of(contract: dict) -> float:
        strike = float(contract["strike_price"])
        return abs(bs_delta(
            spot=spot_price, strike=strike, dte_days=dte_days,
            volatility=realized_vol, option_type=option_type,
        ))

    def is_otm(contract: dict) -> bool:
        strike = float(contract["strike_price"])
        return strike < spot_price if is_bull_put else strike > spot_price

    same_exp_by_strike = {float(c["strike_price"]): c for c in exp_contracts}

    def snap_long_strike(short_strike: float) -> float | None:
        # Long leg: `spread_width_dollars` further out-of-the-money than the
        # short strike, snapped to the closest available strike — but ONLY
        # among strikes strictly further OTM than the short. The previous
        # closest-anywhere snap could land on the short strike itself at the
        # chain edge (GLD 2026-09-09: chain topped out at the short → same-
        # strike "spread", credit 0.00 every cycle) or even invert the
        # structure. No further-OTM strike = this short has no spread here.
        target = (
            short_strike - limits.spread_width_dollars
            if is_bull_put
            else short_strike + limits.spread_width_dollars
        )
        further = [
            k for k in same_exp_by_strike
            if (k < short_strike if is_bull_put else k > short_strike)
        ]
        if not further:
            return None
        return min(further, key=lambda k: abs(k - target))

    # Delta is computed in-process (no quotes needed), so shortlist strikes
    # BEFORE fetching snapshots: with the chain now paginated in full, a
    # dense expiration can hold 300+ contracts, and quoting all of them per
    # ticker per cycle is pointless load on the snapshot endpoint. The
    # shortlist is the OTM strikes nearest the target delta plus each one's
    # snapped long leg — anything liquidity might still reject is well past
    # what a sane short strike could be.
    otm_by_delta = sorted(
        ((c, delta_of(c)) for c in exp_contracts if is_otm(c)),
        key=lambda cd: abs(cd[1] - limits.short_leg_target_delta),
    )
    # Chain-edge shorts (no strictly-further-OTM long available) are excluded
    # from the shortlist before quoting — they can never form a spread.
    shortlist = [
        (c, d) for c, d in otm_by_delta
        if snap_long_strike(float(c["strike_price"])) is not None
    ][:SHORT_CANDIDATE_COUNT]
    snapshot_symbols: list[str] = []
    for c, _ in shortlist:
        long_c = same_exp_by_strike[snap_long_strike(float(c["strike_price"]))]
        for symbol in (c["symbol"], long_c["symbol"]):
            if symbol not in snapshot_symbols:
                snapshot_symbols.append(symbol)
    snap_by_symbol = await _fetch_snapshots(mcp, snapshot_symbols)

    # The short leg must be OTM relative to spot. The delta sort would
    # normally guarantee that, but only among *liquidity-passing* strikes: on
    # the indicative feed the OTM side of a thin chain can quote too wide to
    # pass, leaving only ITM strikes as candidates — and an ITM short's "credit"
    # is dominated by intrinsic value on stale mids, not premium (seen live
    # 2026-09-02 and 2026-09-03: XLK bear calls ~7 points ITM offered at
    # credit > max loss). If no OTM strike is liquid, there is no real spread
    # to build here.
    liquid_candidates = [
        (c, d) for c, d in shortlist
        if _passes_liquidity(c, snap_by_symbol.get(c["symbol"], {}))
    ]
    if not liquid_candidates:
        logger.info(
            "%s %s chain has %d strikes but none are both OTM and liquid "
            "(min OI %d, max spread %.0f%%), skipping",
            ticker, chosen_expiration, len(exp_contracts),
            limits.min_open_interest, limits.max_bid_ask_spread_pct * 100,
        )
        return None

    liquid_candidates.sort(key=lambda cd: abs(cd[1] - limits.short_leg_target_delta))

    # Walk the liquid shorts in delta order and take the FIRST whose long leg
    # is actually tradeable. Previously only liquid_candidates[0] was tried,
    # so one junk long-leg quote lost the entire ticker for the cycle
    # (TLT/XLF, every cycle of 2026-09-09). Zero extra API calls: every
    # candidate's long is already in the snapshot batch.
    short_contract = long_contract = None
    short_mid = long_mid = None
    for cand, _d in liquid_candidates:
        cand_strike = float(cand["strike_price"])
        cand_long_strike = snap_long_strike(cand_strike)
        if cand_long_strike is None:
            continue
        cand_long = same_exp_by_strike[cand_long_strike]
        cand_long_snap = snap_by_symbol.get(cand_long["symbol"], {})
        if not _passes_liquidity(cand_long, cand_long_snap, max_spread_override=LONG_LEG_MAX_SPREAD_PCT):
            logger.info("%s long leg (%s) fails the liquidity gate, trying next short",
                        ticker, cand_long["symbol"])
            continue
        s_mid = _mid_from_snapshot(snap_by_symbol.get(cand["symbol"], {}))
        l_mid = _mid_from_snapshot(cand_long_snap)
        if s_mid is None or l_mid is None:
            logger.info("Missing quotes for %s %s/%s, trying next short",
                        ticker, cand["symbol"], cand_long["symbol"])
            continue
        short_contract, long_contract = cand, cand_long
        short_mid, long_mid = s_mid, l_mid
        break

    if short_contract is None:
        logger.info("%s: no liquid short with a tradeable long leg this cycle, skipping", ticker)
        return None

    short_strike = float(short_contract["strike_price"])
    target_long_strike = float(long_contract["strike_price"])

    credit_estimate = round((short_mid - long_mid) * 100, 2)  # per 1 contract, $ not cents
    width_dollars = abs(short_strike - target_long_strike) * 100
    max_loss = round(width_dollars - credit_estimate, 2)

    if credit_estimate <= 0:
        logger.info("%s spread has non-positive credit (%.2f), skipping", ticker, credit_estimate)
        return None

    # Real bug caught 2026-08-27: credit_estimate > 0 alone doesn't rule out
    # a nonsensical spread — if credit exceeds the strike width (stale or
    # crossed quotes, or the long strike snapping to something closer than
    # the intended width), max_loss goes negative, meaning "risk-free
    # profit" on paper. A spread whose own defined risk is negative or zero
    # is not a real credit spread and must never reach execution.
    if max_loss <= 0:
        logger.warning(
            "%s spread has non-positive max_loss (%.2f = width %.2f - credit %.2f) "
            "-- almost certainly a stale/bad quote, skipping",
            ticker, max_loss, width_dollars, credit_estimate,
        )
        return None

    return SpreadPlan(
        underlying=ticker,
        direction="bull_put" if is_bull_put else "bear_call",
        expiration=datetime.strptime(chosen_expiration, "%Y-%m-%d").date(),
        short_strike=short_strike,
        long_strike=target_long_strike,
        short_symbol=short_contract["symbol"],
        long_symbol=long_contract["symbol"],
        credit_estimate=credit_estimate,
        max_loss=max_loss,
    )
