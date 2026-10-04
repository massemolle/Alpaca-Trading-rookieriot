"""Premium-buyer cycle — cron :15/:45 during market hours (offset from the
credit bot). Exits first and ungated; entries behind window, halts, caps,
richness gate, judge, rhetoric audit."""
from __future__ import annotations

import asyncio
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s [%(levelname)s] %(message)s",
                    filename=str(Path(__file__).resolve().parent.parent / "state" / "premium.log"))
logger = logging.getLogger(__name__)

import black_scholes
import bot as credit_bot
import db  # noqa: F401
from alpaca_client import AlpacaClient
from mcp_client import AlpacaMCP
import rhetoric
from premium_buyer import book, brier, builder, config as pcfg, executor, reasoner
from spread_builder import _fetch_snapshots, _mid_from_snapshot
from screening.filters import filter_universe
from signals.swing import generate_swing_signals


def _in_entry_window(now: datetime) -> bool:
    hm = now.strftime("%H:%M")
    return pcfg.ENTRY_START_UTC <= hm <= pcfg.ENTRY_END_UTC


async def manage_exits(mcp, client) -> list[str]:
    """-STOP_PCT / +TAKE_PCT on mid; force close on expiry day. Never gated."""
    notes = []
    positions = book.open_positions()
    if not positions:
        return notes
    snaps = await _fetch_snapshots(mcp, [p["symbol"] for p in positions])
    today = datetime.now(timezone.utc).date()
    for p in positions:
        mid = _mid_from_snapshot(snaps.get(p["symbol"], {}))
        if mid is None:
            continue
        paid = float(p["premium_paid"]) / 100  # per-share
        move = (mid - paid) / paid if paid else 0
        reason = None
        if p["expiration"] <= today:
            reason = "expiry_day"
        elif move <= -pcfg.STOP_PCT:
            reason = "stop"
        elif move >= pcfg.TAKE_PCT:
            reason = "take_profit"
        if reason:
            res = await executor.sell_to_close(mcp, p["symbol"], int(p["contracts"]), mid)
            if res is not None:
                fill = res.get("fill_price") or mid
                pnl = round((fill - paid) * 100 * int(p["contracts"]), 2)
                book.close_position(p["id"], reason, pnl)
                notes.append(f"CLOSED {p['underlying']} {reason} pnl ${pnl}")
    return notes


async def cycle() -> None:
    book.ensure_tables()
    client = AlpacaClient()
    market_open = client.get_clock()["is_open"]
    async with AlpacaMCP() as mcp:
        notes = await manage_exits(mcp, client) if market_open else []
        brier.resolve_due(client)

        now = datetime.now(timezone.utc)
        rejections: list[dict] = []
        if not market_open:
            book.journal("skipped", [], [], "Market closed.", [], [])
            print("market closed", *notes)
            return
        if not _in_entry_window(now):
            book.journal("skipped", [], [], "Outside entry window — exits only.", [], [])
            print("outside entry window", *notes)
            return
        if book.realized_today() <= -pcfg.DAILY_LOSS_HALT:
            book.journal("halted", [], [], "Daily loss halt.", [], [])
            print("daily loss halt", *notes)
            return
        budget = pcfg.MAX_POSITIONS - len(book.open_positions())
        if budget <= 0:
            book.journal("skipped", [], [], "Position budget full.", [], [])
            print("budget full", *notes)
            return

        held = {p["underlying"] for p in book.open_positions()}
        cands_screen = filter_universe(pcfg.UNIVERSE, client, rejections_out=rejections)
        signals = [s for s in generate_swing_signals([c.symbol for c in cands_screen], client)
                   if getattr(s, "direction", None) in ("long", "short") and s.ticker not in held]

        candidates = []
        for sig in signals:
            try:
                q = client.get_latest_quote(sig.ticker)
                spot = (q["ask_price"] + q["bid_price"]) / 2
                bars = credit_bot._fetch_daily_bars(client, sig.ticker)
                rv = black_scholes.realized_vol_from_bars(bars)
                plan, why = await builder.build_buy(mcp, sig.ticker, sig.direction, spot, rv)
                if plan is None:
                    rejections.append({"ticker": sig.ticker, "stage": "builder", "reasons": [why]})
                    continue
                candidates.append({
                    "ticker": sig.ticker, "direction": sig.direction,
                    "strength": round(getattr(sig, "strength", 0), 3),
                    "premium": plan.premium, "price_ratio": plan.price_ratio,
                    "dte": (plan.expiration - now.date()).days,
                    "facts": plan.facts, "_plan": plan,
                })
            except Exception:
                logger.exception("candidate build failed for %s", sig.ticker)

        slim = [{k: v for k, v in c.items() if k != "_plan"} for c in candidates]
        outcome = reasoner.decide(slim, budget)
        reasoning = outcome["reasoning"]
        selected = [s for s in outcome["selected"] if any(c["ticker"] == s.get("ticker") for c in candidates)][:budget]

        flags = rhetoric.audit_values(slim, reasoning) + rhetoric.audit_alignment(selected, pcfg.MIN_STATED_P)
        if flags:
            # A judge that misquotes evidence or contradicts itself doesn't trade.
            book.journal("audit_block", slim, selected, reasoning, flags, rejections)
            for c in candidates:  # still record declined predictions for Brier
                book.record_prediction(c["ticker"], c["direction"], None, c["_plan"].facts[3]["value"],
                                       c["_plan"].expiration, taken=False)
            print(f"AUDIT BLOCK: {flags}", *notes)
            return

        by_ticker = {c["ticker"]: c for c in candidates}
        picked = {s["ticker"]: s for s in selected}
        opened = []
        for tkr, c in by_ticker.items():
            plan = c["_plan"]
            spot_val = next(f["value"] for f in plan.facts if f["fact_id"].endswith("_SPOT"))
            if tkr in picked:
                res = await executor.buy(mcp, plan.symbol, 1, plan.mid)
                if res is not None:
                    fill = res.get("fill_price") or plan.mid
                    book.open_position(underlying=tkr, symbol=plan.symbol, right=plan.direction,
                                       strike=plan.strike, expiration=plan.expiration, contracts=1,
                                       premium_paid=round(fill * 100, 2),
                                       stated_p=picked[tkr].get("p_move"),
                                       client_order_id=res.get("client_order_id"),
                                       order_ids=[res.get("id")])
                    opened.append(tkr)
                book.record_prediction(tkr, c["direction"], picked[tkr].get("p_move"),
                                       spot_val, plan.expiration, taken=True)
            else:
                book.record_prediction(tkr, c["direction"], None, spot_val,
                                       plan.expiration, taken=False)

        decision = "opened" if opened else ("abstained" if candidates else "skipped")
        book.journal(decision, slim, selected, reasoning, [], rejections)
        print(f"{decision}: {opened or '-'} | cands {len(candidates)}", *notes)


if __name__ == "__main__":
    asyncio.run(cycle())
