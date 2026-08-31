"""Day-1 forced experiment (2026-08-31, operator-ordered).

Open two 1-contract bull-put verticals (SPY, QQQ) through the NORMAL
execution machinery — spread builder, BOTH risk gates, limit pricing, fill
confirmation, DB recording — bypassing ONLY the signal-quality filters
(trend/vol), which correctly said "no setup" all day in 1st-percentile
realized vol. Rationale: day one must produce real fills, management,
slippage and greeks data; the cost is accepting historically poor premium,
accepted consciously as an experiment cost.

Honesty rules:
- Journaled as decision='manual_experiment', reasoning prefixed [MANUAL
  EXPERIMENT] — never attributed to the AI selector.
- If either RISK gate blocks a leg of the experiment, that leg is dropped,
  not overridden: forcing past signal filters is an experiment; forcing
  past risk gates would be a violation.
- Positions are managed by the normal bot loop afterwards (exits, marks,
  reconciliation) — no special-casing downstream.
"""
from __future__ import annotations

import asyncio
import fcntl
from datetime import datetime, timezone

import black_scholes
import bot
import db
import executor_mcp
import risk_gate
from alpaca_client import AlpacaClient
from config import config
from mcp_client import AlpacaMCP
from pretrade_gate import _daily_pl, pre_trade_check
from screening import correlation_clusters
from spread_builder import build_spread

REASONING = (
    "[MANUAL EXPERIMENT] Operator-ordered day-1 experiment: the signal filters "
    "(trend alignment, realized-vol floor) rejected every setup today — a "
    "defensible no-trade stance in 1st-percentile vol, but day one must "
    "produce execution/management data. Two minimal bull-put verticals opened "
    "deliberately through the full gate+execution path. Not an AI decision."
)

LEGS = [("SPY", "long"), ("QQQ", "long")]  # 'long' signal -> bull_put


async def main() -> None:
    client = AlpacaClient()
    clock = client.get_clock()
    if not clock["is_open"]:
        print("Market closed — aborting experiment.")
        return

    account = client.get_account()
    equity = float(account["equity"])
    _, daily_pl_pct = _daily_pl(account)

    existing_exposure: dict[str, float] = {}
    cluster_exposure: dict[str, float] = {}
    for s in db.get_open_spreads():
        n = int(s.get("contracts") or 1)
        tot = float(s.get("max_loss", 0)) * n
        existing_exposure[s["underlying"]] = existing_exposure.get(s["underlying"], 0) + tot
        cl = correlation_clusters.cluster_for(s["underlying"])
        if cl:
            cluster_exposure[cl] = cluster_exposure.get(cl, 0) + tot

    opened = 0
    async with AlpacaMCP() as mcp:
        for ticker, sig_dir in LEGS:
            print(f"--- {ticker} ({sig_dir} -> bull_put) ---")
            bars = bot._fetch_daily_bars(client, ticker)
            rv = black_scholes.realized_vol_from_bars(bars)
            spot = client.get_latest_quote(ticker)
            spot_mid = (spot["ask_price"] + spot["bid_price"]) / 2
            plan = await build_spread(mcp, ticker, sig_dir, spot_price=spot_mid, realized_vol=rv)
            if plan is None:
                print(f"{ticker}: spread builder returned no viable plan (liquidity/credit floor) — dropped.")
                continue
            print(f"plan: {plan.direction} {plan.short_strike}/{plan.long_strike} exp {plan.expiration} "
                  f"est credit ${plan.credit_estimate:.2f} max loss ${plan.max_loss:.2f}")

            check = risk_gate.check_new_spread(
                equity=equity, daily_pl_pct=daily_pl_pct,
                open_spreads_count=len(db.get_open_spreads()) + opened,
                max_loss=plan.max_loss, expiration=plan.expiration,
                today=datetime.now(timezone.utc).date(),
                existing_exposure=existing_exposure, underlying=ticker,
                cluster_exposure=cluster_exposure,
            )
            if not check.allowed:
                print(f"{ticker}: RISK GATE blocked — {check.reasons} — dropped (never overridden).")
                continue

            gate = await pre_trade_check(mcp, client, plan, opened_this_cycle=opened, contracts=1)
            if not gate.allowed:
                print(f"{ticker}: PRE-TRADE GATE blocked — {gate.reasons} — dropped (never overridden).")
                continue
            plan = gate.plan

            limit_credit = executor_mcp.limit_credit_price(plan.credit_estimate)
            result = await executor_mcp.open_spread(
                mcp, plan, contracts=gate.contracts, client=client, limit_credit=limit_credit,
            )
            status = "open" if result.status in ("filled", "dry_run") else "pending"
            credit = result.fill_credit if result.fill_credit is not None else plan.credit_estimate
            slim = [{"ticker": ticker, "direction": plan.direction, "strength": None,
                     "credit_estimate": plan.credit_estimate, "max_loss": plan.max_loss,
                     "note": "manual experiment — signal filters bypassed, risk gates enforced"}]
            cycle_id = db.record_cycle(slim, "manual_experiment", REASONING)
            db.record_spread_open(
                underlying=plan.underlying, direction=plan.direction,
                expiration=plan.expiration.isoformat(),
                short_strike=plan.short_strike, long_strike=plan.long_strike,
                short_symbol=plan.short_symbol, long_symbol=plan.long_symbol,
                contracts=gate.contracts, credit_received=credit, max_loss=plan.max_loss,
                alpaca_order_ids=result.order_ids, cycle_id=cycle_id, status=status,
                fill_credit=result.fill_credit, client_order_id=result.client_order_id,
                est_credit=plan.credit_estimate,
            )
            db.record_decision_journal(
                cycle_id=cycle_id, candidates=slim, llm_selected=[],
                llm_reasoning=REASONING, shadow_selected=[],
                gate_rejections=[], pre_trade_rejections=[],
            )
            opened += 1
            slip = (f"{(result.fill_credit - plan.credit_estimate):+.2f}"
                    if result.fill_credit is not None else "pending fill")
            print(f"{ticker}: {status.upper()} x{gate.contracts} — est ${plan.credit_estimate:.2f} "
                  f"fill {result.fill_credit} (slippage {slip}) orders={result.order_ids}")

    print(f"=== experiment done: {opened} spread(s) submitted ===")
    for p in client.get_positions():
        print("broker position:", p["symbol"], p["side"], p["qty"])


if __name__ == "__main__":
    with open("state/bot.lock", "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)  # never overlap a cron cycle
        asyncio.run(main())
