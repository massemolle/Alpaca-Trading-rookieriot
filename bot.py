"""Main cycle for the Alpaca AI Trading Agents Hackathon submission.

Pipeline, once per invocation (scheduled ~every 30min during market hours by
Hermes — see run_options_cron.sh):

  1. Manage existing open spreads: pull each one's current mark via MCP,
     apply risk_gate.should_close (profit target / stop), close via MCP if
     triggered, record to Supabase.
  2. Screen for new candidates: reuse trading_bot's vendored screening +
     swing-horizon signals + TrendFilter, unmodified.
  3. For each candidate that clears risk_gate.check_new_spread, build a
     concrete SpreadPlan via MCP (spread_builder).
  4. Hand the surviving, risk-approved candidates to llm_reasoner — the
     actual "autonomous AI agent" decision of which (if any) to act on.
  5. Open the LLM's selected spread(s) via MCP, record to Supabase.
  6. Record an account snapshot every cycle regardless of whether anything
     traded, so the dashboard's equity curve never has gaps.

Prints a short summary to stdout ONLY when something happened (opened,
closed, or errored) — mirrors trading_bot/run_paper_cron.sh's own
silent-unless-noteworthy convention, since Hermes forwards stdout to
Telegram and an empty-cycle spam every 30 minutes would be exactly the
"the agent is annoying" outcome that pattern was built to avoid.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone

import pandas as pd
from alpaca.data.timeframe import TimeFrame

from alpaca_client import AlpacaClient
from config import config
from screening.universe import get_universe
from screening.filters import filter_universe
from signals.indicators import compute_atr
from signals.swing import generate_swing_signals
from signals.trend_filter import TrendFilter

import black_scholes
import db
import executor_mcp
import llm_reasoner
import risk_gate
from mcp_client import AlpacaMCP
from pretrade_gate import _daily_pl, pre_trade_check
from spread_builder import build_spread

from pathlib import Path

# `basicConfig`'s default StreamHandler writes to stderr, not stdout — but
# run_options_cron.sh redirects stderr into stdout (`2>&1`) before deciding
# whether there's anything worth delivering, so every INFO-level screening
# line (dozens per cycle: "23/503 tickers passed filters", each rejection
# reason, every MCP call) rode along regardless of the docstring's stated
# "silent unless something happened" intent — confirmed directly: a single
# no-op cycle produced 61 lines of output, all delivered as if noteworthy.
# Real, user-visible symptom (2026-08-27): Alex had to ask Hermes to stop
# forwarding these to Telegram entirely ("me llena de mensajes raros") and
# reroute to Discord instead — which only relocates the noise, it doesn't
# fix it. Routing the log handler to a file instead restores the original
# design: stdout carries only the deliberate print(note) calls below.
LOG_DIR = Path(__file__).resolve().parent / "state"
LOG_DIR.mkdir(exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    filename=str(LOG_DIR / "bot.log"),
)
logger = logging.getLogger(__name__)

# Same lookback trading_bot/bot.py uses for its own trend filter — EMA200 +
# a buffer, in calendar days rather than trading days to survive
# weekends/holidays comfortably.
TREND_FILTER_LOOKBACK_DAYS = 400


def _realized_vol_percentile(bars_df: pd.DataFrame) -> float | None:
    """Where this ticker's current realized vol (20-day ATR%) ranks against
    its own trailing-year distribution — None means "not enough history to
    rank meaningfully," treated as fail-open by callers, same as before.
    Split out from the old _passes_volatility_filter so the adaptive
    threshold below can see every candidate's percentile before deciding
    what bar to hold the whole cycle to (see _apply_trend_and_volatility_filters).
    """
    vol_cfg = config.volatility
    atr = compute_atr(bars_df["high"], bars_df["low"], bars_df["close"], period=vol_cfg.lookback_window)
    atr_pct = (atr / bars_df["close"]).dropna()
    if len(atr_pct) < vol_cfg.lookback_window * 2:
        return None
    return float(atr_pct.rank(pct=True).iloc[-1])


def _fetch_daily_bars(client: AlpacaClient, ticker: str) -> pd.DataFrame:
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=TREND_FILTER_LOOKBACK_DAYS)
    bars = client.get_bars(
        ticker, TimeFrame.Day,
        start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d"),
        limit=300,
    )
    return pd.DataFrame(bars)


def _apply_trend_and_volatility_filters(client: AlpacaClient, signals: list) -> list[tuple]:
    """Returns (signal, realized_vol) pairs for survivors — realized_vol is
    the annualized estimate `spread_builder.build_spread` feeds into
    `black_scholes.bs_delta` as the IV proxy, computed here (not re-fetched
    later) since this is already pulling the daily bars it needs.

    Two passes: trend filter first (unchanged), then the volatility filter
    with an adaptive threshold — see config.VolatilityFilter's docstring.
    The adaptive rule needs every trend-survivor's percentile computed up
    front to decide whether *this cycle* is unusually low-vol across the
    board (relax) versus this one ticker just being quiet (still reject).
    """
    trend_filter = TrendFilter()
    trend_survivors: list[tuple] = []  # (sig, bars_df)
    for sig in signals:
        try:
            bars_df = _fetch_daily_bars(client, sig.ticker)
        except Exception:
            logger.exception("Failed to fetch bars for %s, skipping", sig.ticker)
            continue

        # A real failure mode hit live: get_bars() can return an empty list
        # for a symbol (observed for BAC) -- pd.DataFrame([]) has no columns
        # at all, so bars_df["close"] KeyErrors. The original code only
        # guarded the trend-filter step against this and then immediately
        # crashed the *entire cycle* (not just this ticker) on the very next
        # line, in realized_vol_from_bars -- a single bad symbol took down
        # every other candidate with it. Skip cleanly instead.
        if bars_df.empty or "close" not in bars_df.columns:
            logger.info("%s has no usable daily bars this cycle, skipping", sig.ticker)
            continue

        try:
            trend_result = trend_filter.check(bars_df, sig.direction)
            trend_allowed = trend_result.allowed
        except Exception:
            logger.exception("Trend filter failed for %s, allowing", sig.ticker)
            trend_allowed = True
        if not trend_allowed:
            continue

        trend_survivors.append((sig, bars_df))

    vol_cfg = config.volatility
    min_percentile = vol_cfg.min_percentile

    if vol_cfg.enabled and trend_survivors:
        percentiles: list[float] = []
        for sig, bars_df in trend_survivors:
            try:
                pct = _realized_vol_percentile(bars_df)
            except Exception:
                logger.exception("Volatility percentile failed for %s, treating as unrankable", sig.ticker)
                pct = None
            if pct is not None:
                percentiles.append(pct)

        if percentiles:
            rejection_rate = sum(1 for p in percentiles if p < min_percentile) / len(percentiles)
            if rejection_rate > vol_cfg.max_rejection_rate_before_relax:
                logger.info(
                    "Volatility filter would reject %.0f%% of %d rankable candidates at "
                    "percentile %.2f -- relaxing to %.2f for this cycle only (adaptive rule, "
                    "not a permanent change; see config.VolatilityFilter)",
                    rejection_rate * 100, len(percentiles), min_percentile,
                    vol_cfg.relaxed_min_percentile,
                )
                min_percentile = vol_cfg.relaxed_min_percentile

    kept = []
    for sig, bars_df in trend_survivors:
        if vol_cfg.enabled:
            try:
                pct = _realized_vol_percentile(bars_df)
            except Exception:
                logger.exception("Volatility filter failed for %s, allowing", sig.ticker)
                pct = None
            if pct is not None and pct < min_percentile:
                logger.info(
                    "%s rejected: realized vol percentile %.2f below %.2f",
                    sig.ticker, pct, min_percentile,
                )
                continue

        realized_vol = black_scholes.realized_vol_from_bars(bars_df)
        kept.append((sig, realized_vol))
    return kept


def _optimal_contracts(equity: float, max_loss_per_contract: float, max_risk_pct: float = 0.02) -> int:
    """Size contracts so total max loss stays within risk budget."""
    if max_loss_per_contract <= 0:
        return 1
    dollar_budget = equity * max_risk_pct
    contracts = int(dollar_budget // max_loss_per_contract)
    return max(contracts, 1)


async def manage_open_spreads(mcp: AlpacaMCP) -> list[str]:
    notes = []
    for spread in db.get_open_spreads():
        expiration = datetime.strptime(str(spread["expiration"]), "%Y-%m-%d").date()
        force_close, force_reason = risk_gate.should_force_close(expiration=expiration)

        try:
            mark = await executor_mcp.get_spread_mark(mcp, spread["short_symbol"], spread["long_symbol"])
        except Exception:
            logger.exception("Failed to get mark for spread %s", spread["id"])
            if not force_close:
                continue
            mark = None

        if force_close:
            should_close, reason = True, force_reason
        elif mark is None:
            continue
        else:
            should_close, reason = risk_gate.should_close(
                credit_received=float(spread["credit_received"]),
                current_mark=mark,
            )
        if not should_close:
            continue
        try:
            await executor_mcp.close_spread(
                mcp,
                short_symbol=spread["short_symbol"],
                long_symbol=spread["long_symbol"],
                contracts=spread["contracts"],
            )
            if mark is None:
                # Force-closed without ever getting a fresh mark (quote fetch
                # failed) — still worth closing out ahead of expiration/the
                # contest deadline, but the realized P&L is genuinely unknown
                # until the fill confirms, not silently reported as $0.
                realized_pnl = None
                status = "closed_expiry"
                notes.append(f"Force-closed {spread['underlying']} {spread['direction']}: {reason} (P&L unknown, mark unavailable)")
            else:
                # credit_received/mark are both per-contract (get_spread_mark
                # never multiplies by position size) — multiply by the real
                # contracts held or P&L is understated whenever contracts>1,
                # the same class of bug fixed in the entry path above.
                contracts_held = int(spread.get("contracts") or 1)
                realized_pnl = (float(spread["credit_received"]) - mark) * contracts_held
                status = "closed_expiry" if force_close else ("closed_profit" if realized_pnl > 0 else "closed_stop")
                notes.append(f"Closed {spread['underlying']} {spread['direction']}: {reason} (P&L ${realized_pnl:+.2f})")
            db.record_spread_close(spread["id"], status, realized_pnl)
        except Exception as exc:
            logger.exception("Failed to close spread %s", spread["id"])
            notes.append(f"ERROR closing {spread['underlying']}: {exc}")
    return notes


async def find_candidates(
    mcp: AlpacaMCP, client: AlpacaClient, account: dict, open_count: int
) -> tuple[list[dict], list[dict]]:
    universe = get_universe()
    filtered = filter_universe(universe, client)
    tickers = [c.symbol for c in filtered]
    signals = generate_swing_signals(tickers, client)
    signals_with_vol = _apply_trend_and_volatility_filters(client, signals)

    today = datetime.now(timezone.utc).date()

    existing_exposure: dict[str, float] = {}
    for s in db.get_open_spreads():
        underlying = s["underlying"]
        existing_exposure[underlying] = existing_exposure.get(underlying, 0) + float(s.get("max_loss", 0))

    candidates = []
    gate_rejections: list[dict] = []
    for sig, realized_vol in signals_with_vol:
        try:
            spot = client.get_latest_quote(sig.ticker)
            spot_mid = (spot["ask_price"] + spot["bid_price"]) / 2
            plan = await build_spread(mcp, sig.ticker, sig.direction, spot_price=spot_mid, realized_vol=realized_vol)
        except Exception:
            logger.exception("Failed to build spread for %s", sig.ticker)
            continue
        if plan is None:
            continue
        check = risk_gate.check_new_spread(
            equity=float(account["equity"]),
            daily_pl_pct=float(account.get("daily_pl_pct") or 0.0),
            open_spreads_count=open_count,
            max_loss=plan.max_loss,
            expiration=plan.expiration,
            today=today,
            existing_exposure=existing_exposure,
            underlying=sig.ticker,
        )
        if not check.allowed:
            logger.info("%s rejected by risk gate: %s", sig.ticker, check.reasons)
            gate_rejections.append({"ticker": sig.ticker, "reasons": check.reasons})
            continue
        candidates.append({
            "ticker": sig.ticker,
            "direction": sig.direction,
            "strength": sig.strength,
            "signal_reasoning": sig.reasoning,
            "credit_estimate": plan.credit_estimate,
            "max_loss": plan.max_loss,
            "expiration": plan.expiration.isoformat(),
            "_plan": plan,
        })
    return candidates, gate_rejections


def _shadow_select(candidates: list[dict], remaining_budget: int) -> list[str]:
    """Mechanical baseline: rank by strength * (credit/max_loss), pick top N."""
    if not candidates or remaining_budget <= 0:
        return []
    scored = []
    for c in candidates:
        credit = c.get("credit_estimate", 0)
        max_loss = c.get("max_loss", 1)
        strength = c.get("strength", 0)
        rr = credit / max_loss if max_loss > 0 else 0
        score = strength * rr
        scored.append((c["ticker"], score))
    scored.sort(key=lambda x: x[1], reverse=True)
    return [ticker for ticker, _ in scored[:remaining_budget]]


async def run_cycle() -> None:
    client = AlpacaClient()
    account = client.get_account()
    daily_pl, daily_pl_pct = _daily_pl(account)
    account["daily_pl"] = daily_pl
    account["daily_pl_pct"] = daily_pl_pct

    async with AlpacaMCP() as mcp:
        close_notes = await manage_open_spreads(mcp)

        open_spreads = db.get_open_spreads()
        remaining_budget = max(0, config.risk.max_concurrent_spreads - len(open_spreads))

        # Defense in depth, added 2026-08-27 after a real incident: this
        # bot is only ever meant to open NEW positions while the market is
        # actually open (the cron schedule already covers that in the
        # common case, but a manual/out-of-schedule invocation has no such
        # guard). Options market orders get rejected by Alpaca outside
        # market hours anyway (confirmed live: HTTP 422, "options market
        # orders are only allowed during market hours") -- checking here
        # avoids wasting a full screening pass building candidates that can
        # never actually execute, and closes the exact gap that produced a
        # phantom "opened" db record that evening (see executor_mcp.py's
        # _extract_order_ids for the other half of that fix). Managing
        # already-open spreads still runs regardless -- force-close-by-
        # deadline shouldn't wait on this check.
        try:
            market_open = client.get_clock()["is_open"]
        except Exception:
            logger.exception("Failed to check market clock, assuming closed (fail safe, not fail open)")
            market_open = False

        open_notes = []
        candidates = []
        slim_candidates: list[dict] = []
        decision = "skipped"
        reasoning = (
            "No eligible candidates this cycle." if market_open
            else "Market is closed — not screening for new candidates this cycle."
        )
        gate_rejections: list[dict] = []
        pre_trade_rejections: list[dict] = []
        shadow_selected: list[str] = []
        llm_selected: list[str] = []
        cycle_id: int | None = None

        if remaining_budget > 0 and market_open:
            candidates, gate_rejections = await find_candidates(mcp, client, account, len(open_spreads))
            slim_candidates = [{k: v for k, v in c.items() if k != "_plan"} for c in candidates]

            outcome = llm_reasoner.decide(slim_candidates, remaining_budget)
            reasoning = outcome["reasoning"]
            llm_selected = outcome["selected"]
            selected_tickers = set(llm_selected)

            shadow_selected = _shadow_select(slim_candidates, remaining_budget)

            opened_this_cycle = 0
            for c in candidates:
                if c["ticker"] not in selected_tickers:
                    continue
                plan = c["_plan"]
                try:
                    gate = await pre_trade_check(
                        mcp, client, plan, opened_this_cycle=opened_this_cycle,
                    )
                    if not gate.allowed:
                        logger.info("Pre-trade check blocked %s: %s", plan.underlying, gate.reason)
                        open_notes.append(f"Pre-trade check blocked {plan.underlying}: {gate.reason}")
                        pre_trade_rejections.append(
                            {"ticker": c["ticker"], "reasons": gate.reasons, "facts": gate.facts}
                        )
                        continue
                    plan = gate.plan
                    contracts = _optimal_contracts(
                        equity=float(account["equity"]),
                        max_loss_per_contract=plan.max_loss,
                        max_risk_pct=config.risk.max_loss_per_spread_pct,
                    )
                    # Real bug caught in review 2026-08-27: this used to be
                    # computed AFTER open_spread(mcp, plan) was already
                    # called without a contracts= argument, so the real
                    # order on Alpaca was always 1 contract regardless of
                    # what got recorded in the DB — a genuine mismatch
                    # between what actually executed and what we'd report.
                    order_ids = await executor_mcp.open_spread(mcp, plan, contracts=contracts)
                    opened_this_cycle += 1
                    cycle_id = db.record_cycle(slim_candidates, "opened", reasoning)
                    db.record_spread_open(
                        underlying=plan.underlying,
                        direction=plan.direction,
                        expiration=plan.expiration.isoformat(),
                        short_strike=plan.short_strike,
                        long_strike=plan.long_strike,
                        short_symbol=plan.short_symbol,
                        long_symbol=plan.long_symbol,
                        contracts=contracts,
                        credit_received=plan.credit_estimate,
                        max_loss=plan.max_loss,
                        alpaca_order_ids=order_ids,
                        cycle_id=cycle_id,
                    )
                    open_notes.append(
                        f"Opened {plan.underlying} {plan.direction} x{contracts} contract(s): "
                        f"credit ${plan.credit_estimate * contracts:.2f} total "
                        f"(${plan.credit_estimate:.2f}/contract), "
                        f"max loss ${plan.max_loss * contracts:.2f} total"
                    )
                    decision = "opened"
                except Exception as exc:
                    logger.exception("Failed to open spread for %s", plan.underlying)
                    open_notes.append(f"ERROR opening {plan.underlying}: {exc}")
                    decision = "error"

        if decision == "skipped":
            cycle_id = db.record_cycle(slim_candidates, decision, reasoning)

        if cycle_id is not None:
            db.record_decision_journal(
                cycle_id=cycle_id,
                candidates=slim_candidates,
                llm_selected=llm_selected,
                llm_reasoning=reasoning,
                shadow_selected=shadow_selected,
                gate_rejections=gate_rejections,
                pre_trade_rejections=pre_trade_rejections,
            )

        db.record_account_snapshot(
            equity=float(account["equity"]),
            last_equity=float(account.get("last_equity")) if account.get("last_equity") else None,
            cash=float(account.get("cash")) if account.get("cash") else None,
            open_spreads_count=len(db.get_open_spreads()),
            daily_pl=float(account.get("daily_pl")) if account.get("daily_pl") else None,
            daily_pl_pct=float(account.get("daily_pl_pct")) if account.get("daily_pl_pct") else None,
        )

        for note in close_notes + open_notes:
            print(note)


if __name__ == "__main__":
    asyncio.run(run_cycle())
