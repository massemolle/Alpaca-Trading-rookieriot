"""Arm-3 cycle: slightly-ITM long singles behind the 15-gate ladder.
Cron :10/:40 (offset from both other sleeves). Exits run first, ungated."""
from __future__ import annotations

import asyncio
import logging
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s",
                    filename=str(Path(__file__).resolve().parent.parent / "state" / "ks.log"))
logger = logging.getLogger(__name__)

import black_scholes
import bot as credit_bot
import rhetoric
from alpaca_client import AlpacaClient
from arm_killswitch import book, config as kcfg, gates
from mcp_client import AlpacaMCP
from premium_buyer import executor  # same single-leg execution path
from premium_buyer import reasoner as prem_reasoner
from signals.indicators import compute_atr
from signals.swing import generate_swing_signals
from spread_builder import _fetch_contracts, _fetch_snapshots, _mid_from_snapshot, _passes_liquidity


async def manage_exits(mcp, client) -> list[str]:
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
        try:
            q = client.get_latest_quote(p["underlying"])
            spot = (q["ask_price"] + q["bid_price"]) / 2
        except Exception:
            continue
        dte = (p["expiration"] - today).days
        reason = gates.exit_decision(
            entry_premium=float(p["premium_paid"]) / 100, current_premium=mid,
            spot=spot, stop_spot=float(p["stop_spot"]), right=p["right_"], dte=dte)
        if reason:
            res = await executor.sell_to_close(mcp, p["symbol"], int(p["contracts"]), mid)
            if res is not None:
                fill = res.get("fill_price") or mid
                pnl = round((fill - float(p["premium_paid"]) / 100) * 100 * int(p["contracts"]), 2)
                book.close_position(p["id"], reason, pnl)
                notes.append(f"CLOSED {p['underlying']} {reason} pnl ${pnl}")
    return notes


async def cycle() -> None:
    book.ensure_tables()
    client = AlpacaClient()
    account = client.get_account()
    equity = float(account["equity"])
    daily_pl = equity - float(account.get("last_equity") or equity)
    market_open = client.get_clock()["is_open"]

    async with AlpacaMCP() as mcp:
        notes = await manage_exits(mcp, client) if market_open else []
        if not market_open:
            book.journal("skipped", [], [], "Market closed.", [])
            print("market closed", *notes)
            return

        pre = gates.pre_model_gates(equity, daily_pl)
        if not pre.allowed:
            book.journal("gated", [], [], "; ".join(pre.reasons), [{"stage": "pre_model", "reasons": pre.reasons}])
            print("pre-model gates:", pre.reasons, *notes)
            return

        rejections: list[dict] = []
        candidates = []
        today = datetime.now(timezone.utc).date()
        for sig in generate_swing_signals(kcfg.UNIVERSE, client):
            if getattr(sig, "direction", None) not in ("long", "short"):
                continue
            right = "call" if sig.direction == "long" else "put"
            try:
                q = client.get_latest_quote(sig.ticker)
                spot = (q["ask_price"] + q["bid_price"]) / 2
                bars = credit_bot._fetch_daily_bars(client, sig.ticker)
                rv = black_scholes.realized_vol_from_bars(bars)
                atr = float(compute_atr(bars["high"], bars["low"], bars["close"]).iloc[-1])
                chain = await _fetch_contracts(mcp, sig.ticker, right,
                                               today + timedelta(days=kcfg.MIN_DTE),
                                               today + timedelta(days=kcfg.MAX_DTE))
                if not chain:
                    rejections.append({"ticker": sig.ticker, "stage": "chain", "reasons": ["no contracts"]})
                    continue

                def dte_of(c):
                    return max((date.fromisoformat(c["expiration_date"]) - today).days, 1)

                scored = sorted(
                    ((c, abs(black_scholes.bs_delta(spot=spot, strike=float(c["strike_price"]),
                                                    dte_days=dte_of(c), volatility=rv, option_type=right)))
                     for c in chain),
                    key=lambda cd: abs(cd[1] - (kcfg.MIN_DELTA + kcfg.MAX_DELTA) / 2))[:6]
                snaps = await _fetch_snapshots(mcp, [c["symbol"] for c, _ in scored])
                for c, delta in scored:
                    snap = snaps.get(c["symbol"], {})
                    if not _passes_liquidity(c, snap):
                        continue
                    mid = _mid_from_snapshot(snap)
                    if mid is None or mid <= 0:
                        continue
                    dte = dte_of(c)
                    strike = float(c["strike_price"])
                    fair = black_scholes.bs_price(spot=spot, strike=strike, dte_days=dte,
                                                  volatility=rv, option_type=right)
                    if fair <= 0:
                        continue
                    premium = mid * 100
                    fair_tomorrow = black_scholes.bs_price(spot=spot, strike=strike,
                                                           dte_days=max(dte - 1, 0.5),
                                                           volatility=rv, option_type=right)
                    theta_day = max((fair - fair_tomorrow) * 100, 0.0)
                    g = gates.order_gates(sig.ticker, right, premium, equity,
                                          mid / fair, theta_day, delta)
                    if not g.allowed:
                        rejections.append({"ticker": sig.ticker, "stage": "order_gates", "reasons": g.reasons})
                        continue
                    stop_spot = spot - kcfg.ATR_STOP_MULT * atr if right == "call" \
                        else spot + kcfg.ATR_STOP_MULT * atr
                    candidates.append({
                        "ticker": sig.ticker, "direction": sig.direction, "right": right,
                        "premium": round(premium, 2), "contracts": g.contracts,
                        "dte": dte, "delta": round(abs(delta), 3),
                        "price_ratio": round(mid / fair, 3),
                        "facts": [
                            {"fact_id": f"{sig.ticker}_PREMIUM", "value": round(premium, 2),
                             "source": "alpaca_mcp_option_snapshot", "quality": "indicative_delayed",
                             "derivation": "mid x 100"},
                            {"fact_id": f"{sig.ticker}_DELTA", "value": round(abs(delta), 3),
                             "source": "computed", "quality": "computed", "derivation": "black_scholes @ RV"},
                            {"fact_id": f"{sig.ticker}_PRICE_RATIO", "value": round(mid / fair, 3),
                             "source": "computed", "quality": "computed", "derivation": "mid / BS fair"},
                            {"fact_id": f"{sig.ticker}_DTE", "value": dte, "source": "computed",
                             "quality": "computed", "derivation": None},
                        ],
                        "_sym": c["symbol"], "_strike": strike, "_mid": mid,
                        "_exp": date.fromisoformat(c["expiration_date"]),
                        "_spot": spot, "_atr": atr, "_stop": stop_spot,
                    })
                    break  # one contract per ticker per cycle
            except Exception:
                logger.exception("candidate build failed for %s", sig.ticker)

        slim = [{k: v for k, v in c.items() if not k.startswith("_")} for c in candidates]
        budget = kcfg.MAX_POSITIONS - len(book.open_positions())
        outcome = prem_reasoner.decide(slim, budget) if slim else {"selected": [], "reasoning": "No candidates."}
        reasoning = outcome["reasoning"]
        selected = [s for s in outcome["selected"] if any(c["ticker"] == s.get("ticker") for c in candidates)][:budget]
        flags = rhetoric.audit_values(slim, reasoning) + rhetoric.audit_alignment(selected, 0.55)
        if flags:
            book.journal("audit_block", slim, selected, f"[RHETORIC BLOCK: {flags}] {reasoning}", rejections)
            print("AUDIT BLOCK", flags, *notes)
            return

        by_t = {c["ticker"]: c for c in candidates}
        opened = []
        for s in selected:
            c = by_t[s["ticker"]]
            res = await executor.buy(mcp, c["_sym"], c["contracts"], c["_mid"])
            if res is not None:
                fill = res.get("fill_price") or c["_mid"]
                book.open_position(underlying=c["ticker"], symbol=c["_sym"], right=c["right"],
                                   strike=c["_strike"], expiration=c["_exp"], contracts=c["contracts"],
                                   premium_paid=round(fill * 100, 2), entry_spot=c["_spot"],
                                   atr=c["_atr"], stop_spot=c["_stop"], stated_p=s.get("p_move"),
                                   client_order_id=res.get("client_order_id"))
                opened.append(c["ticker"])
        decision = "opened" if opened else ("abstained" if candidates else "skipped")
        book.journal(decision, slim, selected, reasoning, rejections)
        print(f"{decision}: {opened or '-'} | cands {len(candidates)}", *notes)


if __name__ == "__main__":
    asyncio.run(cycle())
