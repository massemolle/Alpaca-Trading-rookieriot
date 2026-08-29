"""Main cycle for the Alpaca AI Trading Agents Hackathon submission.

Pipeline, once per invocation (scheduled ~every 30min during market hours by
Hermes — see run_options_cron.sh):

  0. Reconcile broker positions vs local book — block entries on mismatch.
  1. Manage existing open/pending spreads (only while market is open for
     ordinary closes; force-close still attempted when market open).
  2. Screen ETF universe → swing signals (neutral rejected) → trend/vol
     filters → build spreads → first risk gate.
  3. Build an immutable executable candidate menu (with sized contracts).
  4. LLM + mechanical + random select from the SAME menu.
  5. Final quantity-aware pre-trade gate → bounded limit order → fill track.
  6. Shadow counterfactuals on the same menu; account snapshot from fresh
     broker equity.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
from alpaca.data.timeframe import TimeFrame

import benchmark
import black_scholes
import db
import executor_mcp
import llm_reasoner
import reconciler
import risk_gate
import shadow_book
from alpaca_client import AlpacaClient
from config import config
from mcp_client import AlpacaMCP
from pretrade_gate import _daily_pl, pre_trade_check
from screening.filters import filter_universe
from screening.universe import get_universe
from selector import aggregate_max_loss, shadow_select
from signals.indicators import compute_atr
from signals.swing import generate_swing_signals
from signals.trend_filter import TrendFilter
from sizing import optimal_contracts
from spread_builder import build_spread

LOG_DIR = Path(__file__).resolve().parent / "state"
LOG_DIR.mkdir(exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    filename=str(LOG_DIR / "bot.log"),
)
logger = logging.getLogger(__name__)

TREND_FILTER_LOOKBACK_DAYS = 400


def _realized_vol_percentile(bars_df: pd.DataFrame) -> float | None:
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
    trend_filter = TrendFilter()
    trend_survivors: list[tuple] = []
    for sig in signals:
        try:
            bars_df = _fetch_daily_bars(client, sig.ticker)
        except Exception:
            logger.exception("Failed to fetch bars for %s, skipping", sig.ticker)
            continue

        if bars_df.empty or "close" not in bars_df.columns:
            logger.info("%s has no usable daily bars this cycle, skipping", sig.ticker)
            continue

        try:
            trend_result = trend_filter.check(bars_df, sig.direction)
            trend_allowed = trend_result.allowed
        except Exception:
            # Fail-closed: unverified trend alignment must not trade.
            logger.exception("Trend filter failed for %s, rejecting", sig.ticker)
            continue
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
                logger.exception("Volatility percentile failed for %s", sig.ticker)
                pct = None
            if pct is not None:
                percentiles.append(pct)

        if percentiles:
            rejection_rate = sum(1 for p in percentiles if p < min_percentile) / len(percentiles)
            if rejection_rate > vol_cfg.max_rejection_rate_before_relax:
                logger.info(
                    "Volatility filter would reject %.0f%% — relaxing to %.2f this cycle",
                    rejection_rate * 100, vol_cfg.relaxed_min_percentile,
                )
                min_percentile = vol_cfg.relaxed_min_percentile

    kept = []
    for sig, bars_df in trend_survivors:
        if vol_cfg.enabled:
            try:
                pct = _realized_vol_percentile(bars_df)
            except Exception:
                logger.exception("Volatility filter failed for %s, rejecting", sig.ticker)
                continue
            if pct is None:
                logger.info("%s rejected: realized vol percentile unrankable", sig.ticker)
                continue
            if pct < min_percentile:
                logger.info(
                    "%s rejected: realized vol percentile %.2f below %.2f",
                    sig.ticker, pct, min_percentile,
                )
                continue

        realized_vol = black_scholes.realized_vol_from_bars(bars_df)
        kept.append((sig, realized_vol))
    return kept


async def manage_open_spreads(
    mcp: AlpacaMCP,
    client: AlpacaClient,
    *,
    market_open: bool,
) -> list[str]:
    notes = []
    for spread in db.get_manageable_spreads():
        status = spread.get("status")
        # Pending: try to resolve fill state before managing exits.
        if status == "pending":
            order_ids = spread.get("alpaca_order_ids") or []
            if isinstance(order_ids, str):
                import json
                try:
                    order_ids = json.loads(order_ids)
                except Exception:
                    order_ids = []
            if order_ids and hasattr(client, "get_order"):
                try:
                    order = client.get_order(str(order_ids[0]))
                    ost = str(order.get("status") or "").lower()
                    if ost in executor_mcp.FILLED_STATUSES:
                        fill_px = order.get("filled_avg_price")
                        fill_credit = (
                            round(float(fill_px) * 100, 2) if fill_px is not None else None
                        )
                        db.update_spread_status(
                            spread["id"], "open", fill_credit=fill_credit,
                        )
                        spread = {**spread, "status": "open", "credit_received": fill_credit or spread["credit_received"]}
                        notes.append(f"Pending #{spread['id']} filled → open")
                    elif ost in executor_mcp.TERMINAL_BAD:
                        db.update_spread_status(spread["id"], "rejected")
                        notes.append(f"Pending #{spread['id']} rejected ({ost})")
                        continue
                    else:
                        continue  # still pending
                except Exception:
                    logger.exception("Failed to resolve pending spread %s", spread["id"])
                    continue
            else:
                continue

        expiration = datetime.strptime(str(spread["expiration"]), "%Y-%m-%d").date()
        force_close, force_reason = risk_gate.should_force_close(expiration=expiration)

        # Ordinary closes require market hours; force-close also requires open
        # session so the limit order can be accepted (US options RTH).
        if not market_open:
            if force_close:
                notes.append(
                    f"Force-close pending for {spread['underlying']} ({force_reason}) "
                    f"— market closed, will retry after open"
                )
            continue

        try:
            mark = await executor_mcp.get_spread_mark(
                mcp, spread["short_symbol"], spread["long_symbol"]
            )
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
            limit_debit = (
                executor_mcp.limit_debit_price(mark)
                if mark is not None
                else executor_mcp.limit_debit_price(float(spread["credit_received"]) * 2)
            )
            result = await executor_mcp.close_spread(
                mcp,
                short_symbol=spread["short_symbol"],
                long_symbol=spread["long_symbol"],
                contracts=int(spread.get("contracts") or 1),
                client=client,
                limit_debit=limit_debit,
                underlying=spread["underlying"],
                direction=spread["direction"],
            )
            contracts_held = int(spread.get("contracts") or 1)
            close_debit = result.fill_credit if result.fill_credit is not None else mark
            if close_debit is None:
                realized_pnl = None
                status = "closed_expiry" if force_close else "closed_pending"
                notes.append(
                    f"Close submitted {spread['underlying']} {spread['direction']}: "
                    f"{reason} (P&L unknown)"
                )
            else:
                realized_pnl = (float(spread["credit_received"]) - close_debit) * contracts_held
                status = (
                    "closed_expiry" if force_close
                    else ("closed_profit" if realized_pnl > 0 else "closed_stop")
                )
                notes.append(
                    f"Closed {spread['underlying']} {spread['direction']}: "
                    f"{reason} (P&L ${realized_pnl:+.2f})"
                )
            if result.status == "pending" and realized_pnl is None:
                db.update_spread_status(
                    spread["id"], "pending_close",
                    alpaca_order_ids=result.order_ids,
                )
            else:
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
    # Strategy freeze: neutral never becomes a bear-call by accident.
    signals = [s for s in signals if getattr(s, "direction", None) in ("long", "short")]
    signals_with_vol = _apply_trend_and_volatility_filters(client, signals)

    today = datetime.now(timezone.utc).date()

    existing_exposure: dict[str, float] = {}
    for s in db.get_open_spreads():
        underlying = s["underlying"]
        n = int(s.get("contracts") or 1)
        existing_exposure[underlying] = (
            existing_exposure.get(underlying, 0) + float(s.get("max_loss", 0)) * n
        )

    candidates = []
    gate_rejections: list[dict] = []
    equity = float(account["equity"])
    for sig, realized_vol in signals_with_vol:
        try:
            spot = client.get_latest_quote(sig.ticker)
            spot_mid = (spot["ask_price"] + spot["bid_price"]) / 2
            plan = await build_spread(
                mcp, sig.ticker, sig.direction,
                spot_price=spot_mid, realized_vol=realized_vol,
            )
        except Exception:
            logger.exception("Failed to build spread for %s", sig.ticker)
            continue
        if plan is None:
            continue

        contracts = optimal_contracts(
            equity=equity,
            max_loss_per_contract=plan.max_loss,
            max_risk_pct=config.risk.max_loss_per_spread_pct,
            max_contracts=config.risk.max_contracts_per_spread,
        )
        if contracts < 1:
            gate_rejections.append({
                "ticker": sig.ticker,
                "reasons": [f"1-contract max loss ${plan.max_loss:.2f} exceeds risk budget"],
            })
            continue

        total_max_loss = plan.max_loss * contracts
        check = risk_gate.check_new_spread(
            equity=equity,
            daily_pl_pct=float(account.get("daily_pl_pct") or 0.0),
            open_spreads_count=open_count,
            max_loss=total_max_loss,
            expiration=plan.expiration,
            today=today,
            existing_exposure=existing_exposure,
            underlying=sig.ticker,
        )
        if not check.allowed:
            logger.info("%s rejected by risk gate: %s", sig.ticker, check.reasons)
            gate_rejections.append({"ticker": sig.ticker, "reasons": check.reasons})
            continue

        as_of = datetime.now(timezone.utc).isoformat()
        tkr = sig.ticker
        facts = [
            {"fact_id": f"{tkr}_SIGNAL_STRENGTH", "value": sig.strength, "as_of": as_of,
             "source": "signals.swing", "quality": "computed", "derivation": None},
            {"fact_id": f"{tkr}_REALIZED_VOL", "value": round(float(realized_vol), 4), "as_of": as_of,
             "source": "signals.indicators", "quality": "computed",
             "derivation": "20d ATR% annualized — used as IV proxy (no broker Greeks on this feed)"},
            {"fact_id": f"{tkr}_SPOT_MID", "value": round(spot_mid, 2), "as_of": as_of,
             "source": "alpaca_stock_quote", "quality": "realtime_iex", "derivation": "bid/ask mid"},
            {"fact_id": f"{tkr}_CREDIT_EST", "value": plan.credit_estimate, "as_of": as_of,
             "source": "alpaca_mcp_option_snapshot", "quality": "indicative_delayed",
             "derivation": "(short mid - long mid) x 100, per contract"},
            {"fact_id": f"{tkr}_MAX_LOSS", "value": plan.max_loss, "as_of": as_of,
             "source": "computed", "quality": "computed", "derivation": "strike width x 100 - credit"},
            {"fact_id": f"{tkr}_CONTRACTS", "value": contracts, "as_of": as_of,
             "source": "sizing.optimal_contracts", "quality": "computed",
             "derivation": "floor(equity * max_loss_pct / max_loss_per_contract)"},
            {"fact_id": f"{tkr}_DTE", "value": (plan.expiration - today).days, "as_of": as_of,
             "source": "computed", "quality": "computed", "derivation": "expiration - today, in code"},
        ]
        candidates.append({
            "ticker": sig.ticker,
            "direction": sig.direction,
            "strength": sig.strength,
            "signal_reasoning": sig.reasoning,
            "credit_estimate": plan.credit_estimate,
            "max_loss": plan.max_loss,
            "contracts": contracts,
            "expiration": plan.expiration.isoformat(),
            "facts": facts,
            "_plan": plan,
        })
    return candidates, gate_rejections


async def run_cycle() -> None:
    client = AlpacaClient()

    try:
        market_open = client.get_clock()["is_open"]
    except Exception:
        logger.exception("Failed to check market clock, assuming closed (fail safe)")
        market_open = False

    recon = reconciler.reconcile(client, block_on_mismatch=True)
    if not recon.ok:
        print(f"RECONCILE BLOCK: {recon.reason}")
        # Still snapshot so the dashboard shows the halt.
        try:
            account = client.get_account()
            daily_pl, daily_pl_pct = _daily_pl(account)
            db.record_account_snapshot(
                equity=float(account["equity"]),
                last_equity=float(account.get("last_equity")) if account.get("last_equity") else None,
                cash=float(account.get("cash")) if account.get("cash") else None,
                open_spreads_count=len(db.get_open_spreads()),
                daily_pl=daily_pl,
                daily_pl_pct=daily_pl_pct,
                spy_price=benchmark.spy_mid(client),
            )
            db.record_cycle([], "reconcile_block", recon.reason or "broker/DB mismatch")
        except Exception:
            logger.exception("Failed to record reconcile-block snapshot")
        return

    account = client.get_account()
    daily_pl, daily_pl_pct = _daily_pl(account)
    account["daily_pl"] = daily_pl
    account["daily_pl_pct"] = daily_pl_pct

    async with AlpacaMCP() as mcp:
        close_notes = await manage_open_spreads(mcp, client, market_open=market_open)
        await shadow_book.manage_open(mcp)

        open_spreads = db.get_open_spreads()
        remaining_budget = max(0, config.risk.max_concurrent_spreads - len(open_spreads))

        open_notes: list[str] = []
        candidates: list[dict] = []
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
        error_text: str | None = None
        counterfactual_gate: list[dict] = []

        if remaining_budget > 0 and market_open:
            candidates, gate_rejections = await find_candidates(
                mcp, client, account, len(open_spreads),
            )
            # Immutable executable menu shared by LLM / shadow / random.
            slim_candidates = [{k: v for k, v in c.items() if k != "_plan"} for c in candidates]

            outcome = llm_reasoner.decide(slim_candidates, remaining_budget)
            reasoning = outcome["reasoning"]
            # Hard-cap LLM selection to remaining_budget (prompt alone is insufficient).
            llm_selected = list(outcome["selected"])[:remaining_budget]
            # Drop any ticker not in the menu.
            menu_tickers = {c["ticker"] for c in slim_candidates}
            llm_selected = [t for t in llm_selected if t in menu_tickers]

            llm_risk = aggregate_max_loss(slim_candidates, llm_selected)
            shadow_selected = shadow_select(
                slim_candidates, remaining_budget, max_aggregate_loss=llm_risk or None,
            )

            opened_this_cycle = 0
            for c in candidates:
                if c["ticker"] not in set(llm_selected):
                    continue
                plan = c["_plan"]
                try:
                    gate = await pre_trade_check(
                        mcp, client, plan,
                        opened_this_cycle=opened_this_cycle,
                        contracts=c.get("contracts"),
                    )
                    if not gate.allowed:
                        logger.info("Pre-trade check blocked %s: %s", plan.underlying, gate.reason)
                        open_notes.append(f"Pre-trade check blocked {plan.underlying}: {gate.reason}")
                        pre_trade_rejections.append(
                            {"ticker": c["ticker"], "reasons": gate.reasons, "facts": gate.facts}
                        )
                        continue
                    plan = gate.plan
                    contracts = gate.contracts
                    limit_credit = executor_mcp.limit_credit_price(plan.credit_estimate)
                    result = await executor_mcp.open_spread(
                        mcp, plan, contracts=contracts,
                        client=client, limit_credit=limit_credit,
                    )
                    opened_this_cycle += 1
                    status = "open" if result.status in ("filled", "dry_run") else "pending"
                    credit = result.fill_credit if result.fill_credit is not None else plan.credit_estimate
                    cycle_id = db.record_cycle(slim_candidates, "opened", reasoning)
                    try:
                        db.record_spread_open(
                            underlying=plan.underlying,
                            direction=plan.direction,
                            expiration=plan.expiration.isoformat(),
                            short_strike=plan.short_strike,
                            long_strike=plan.long_strike,
                            short_symbol=plan.short_symbol,
                            long_symbol=plan.long_symbol,
                            contracts=contracts,
                            credit_received=credit,
                            max_loss=plan.max_loss,
                            alpaca_order_ids=result.order_ids,
                            cycle_id=cycle_id,
                            status=status,
                            fill_credit=result.fill_credit,
                            client_order_id=result.client_order_id,
                        )
                    except Exception:
                        # Order may exist at broker — never silently drop.
                        logger.exception(
                            "DB write failed after order %s — RECONCILE REQUIRED",
                            result.order_ids,
                        )
                        open_notes.append(
                            f"CRITICAL: order placed {result.order_ids} but DB write failed "
                            f"for {plan.underlying} — reconcile manually"
                        )
                        decision = "error"
                        error_text = "db_write_after_submit_failed"
                        raise
                    open_notes.append(
                        f"{'Opened' if status == 'open' else 'Submitted'} "
                        f"{plan.underlying} {plan.direction} x{contracts}: "
                        f"credit ${credit * contracts:.2f} total "
                        f"(${credit:.2f}/contract), "
                        f"max loss ${plan.max_loss * contracts:.2f} total "
                        f"[{status}]"
                    )
                    decision = "opened"
                except Exception as exc:
                    logger.exception("Failed to open spread for %s", plan.underlying)
                    open_notes.append(f"ERROR opening {plan.underlying}: {exc}")
                    decision = "error"
                    error_text = f"{type(exc).__name__}: {exc}"

            if decision == "skipped" and slim_candidates and not llm_selected:
                decision = "abstained"
            elif decision == "skipped" and slim_candidates and llm_selected and opened_this_cycle == 0:
                decision = "gate_blocked"

            # Record whether each counterfactual pick would also pass a fresh gate
            # (diagnostic — does not place orders).
            for ticker in set(shadow_selected) - set(llm_selected):
                cand = next((c for c in candidates if c["ticker"] == ticker), None)
                if cand is None:
                    continue
                try:
                    gate = await pre_trade_check(
                        mcp, client, cand["_plan"],
                        opened_this_cycle=opened_this_cycle,
                        contracts=cand.get("contracts"),
                    )
                    counterfactual_gate.append({
                        "ticker": ticker,
                        "allowed": gate.allowed,
                        "reasons": gate.reasons,
                    })
                except Exception as exc:
                    counterfactual_gate.append({
                        "ticker": ticker,
                        "allowed": False,
                        "reasons": [str(exc)],
                    })

        if cycle_id is None:
            cycle_id = db.record_cycle(slim_candidates, decision, reasoning, error=error_text)

        # Attach counterfactual gate results into pre_trade_rejections journal.
        if counterfactual_gate:
            pre_trade_rejections.append({"counterfactual_gate": counterfactual_gate})

        db.record_decision_journal(
            cycle_id=cycle_id,
            candidates=slim_candidates,
            llm_selected=llm_selected,
            llm_reasoning=reasoning,
            shadow_selected=shadow_selected,
            gate_rejections=gate_rejections,
            pre_trade_rejections=pre_trade_rejections,
        )

        shadow_book.open_counterfactuals(
            cycle_id=cycle_id,
            candidates=candidates,
            llm_selected=llm_selected,
            shadow_selected=shadow_selected,
            sizing_fn=lambda **kw: optimal_contracts(
                equity=kw["equity"],
                max_loss_per_contract=kw["max_loss_per_contract"],
                max_risk_pct=kw["max_risk_pct"],
                max_contracts=config.risk.max_contracts_per_spread,
            ),
            equity=float(account["equity"]),
            max_risk_pct=config.risk.max_loss_per_spread_pct,
        )

        # Fresh broker equity AFTER any fills this cycle.
        try:
            fresh = client.get_account()
            f_pl, f_pl_pct = _daily_pl(fresh)
        except Exception:
            logger.exception("Failed to refresh account for snapshot; using cycle-start")
            fresh = account
            f_pl, f_pl_pct = daily_pl, daily_pl_pct

        db.record_account_snapshot(
            equity=float(fresh["equity"]),
            last_equity=float(fresh.get("last_equity")) if fresh.get("last_equity") else None,
            cash=float(fresh.get("cash")) if fresh.get("cash") else None,
            open_spreads_count=len(db.get_open_spreads()),
            daily_pl=f_pl,
            daily_pl_pct=f_pl_pct,
            spy_price=benchmark.spy_mid(client),
        )

        for note in close_notes + open_notes:
            print(note)


if __name__ == "__main__":
    asyncio.run(run_cycle())
