"""Arm-4 cycle: deterministic council on long US equities. Cron :20/:50.
Exits first (any CRITICAL finding exits the full position), then the
5-stage candidate pipeline, then the 7-stage council, then sizing + gate."""
from __future__ import annotations

import hashlib
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s",
                    filename=str(Path(__file__).resolve().parent.parent / "state" / "council.log"))
logger = logging.getLogger(__name__)

import requests

import bot as credit_bot
from alpaca_client import AlpacaClient
from arm_council import book, config as ccfg, council, features

BASE = os.environ.get("ALPACA_BASE_URL", "https://paper-api.alpaca.markets")


def _headers():
    return {"APCA-API-KEY-ID": os.environ["ALPACA_API_KEY"],
            "APCA-API-SECRET-KEY": os.environ["ALPACA_SECRET_KEY"]}


def _cid(action: str, symbol: str) -> str:
    window = datetime.now(timezone.utc).strftime("%Y%m%d%H")
    return f"council-{action}-{hashlib.sha1(f'{symbol}|{window}'.encode()).hexdigest()[:10]}"


def equity_order(symbol: str, qty: int, side: str) -> dict | None:
    cid = _cid(side, symbol)
    if ccfg.DRY_RUN:
        logger.info("DRY_RUN: would %s %s x%s (%s)", side, symbol, qty, cid)
        return {"id": f"dryrun-{cid}", "client_order_id": cid, "status": "dry_run"}
    r = requests.post(f"{BASE}/v2/orders", headers=_headers(), timeout=15, json={
        "symbol": symbol, "qty": str(qty), "side": side, "type": "market",
        "time_in_force": "day", "client_order_id": cid})
    if r.status_code >= 400:
        logger.error("council %s %s failed: %s %s", side, symbol, r.status_code, r.text[:200])
        return None
    return r.json()


def snapshot_for(client: AlpacaClient, symbol: str):
    bars = credit_bot._fetch_daily_bars(client, symbol)
    q = client.get_latest_quote(symbol)
    return features.snapshot_from_bars(symbol, bars, q.get("bid_price") or 0, q.get("ask_price") or 0)


def main() -> None:
    book.ensure_tables()
    client = AlpacaClient()
    if not client.get_clock()["is_open"]:
        print("market closed")
        return
    account = client.get_account()
    equity = float(account["equity"])
    cash = float(account.get("cash") or equity)

    # ---- exits first, ungated ------------------------------------------
    notes = []
    for p in book.open_positions():
        try:
            s = snapshot_for(client, p["symbol"])
            if s is None:
                continue
            pnl_pct = (s.price - float(p["entry_px"])) / float(p["entry_px"]) * 100
            reason = council.exit_decision(pnl_pct, s.momentum, s.rsi14,
                                           s.liquidity_usd, council.scoring.composite_risk(s))
            if reason:
                res = equity_order(p["symbol"], int(p["qty"]), "sell")
                if res is not None and res.get("status") != "dry_run":
                    pnl = round((s.price - float(p["entry_px"])) * float(p["qty"]), 2)
                    book.close_position(p["id"], reason, pnl)
                    notes.append(f"CLOSED {p['symbol']} {reason} pnl ${pnl}")
        except Exception:
            logger.exception("exit check failed for %s", p["symbol"])

    held = {p["symbol"] for p in book.open_positions()}
    budget = ccfg.MAX_OPEN_POSITIONS - len(held)
    if budget <= 0:
        print("position budget full", *notes)
        return

    # ---- candidate pipeline + council ----------------------------------
    scored = []
    for sym in ccfg.UNIVERSE:
        if sym in held:
            continue
        try:
            s = snapshot_for(client, sym)
            if s is None:
                continue
            if s.liquidity_usd < ccfg.MIN_LIQUIDITY_USD or s.spread_bps > ccfg.MAX_SPREAD_BPS:
                continue
            mfs, meta = council.scoring.multi_factor_score(s)
            if mfs < min(ccfg.CANDIDATE_FLOOR, ccfg.MIN_OPPORTUNITY) or meta["rr"] < ccfg.MIN_RR:
                continue
            scored.append((mfs, s))
        except Exception:
            logger.exception("snapshot failed for %s", sym)
    scored.sort(key=lambda x: (-x[0], x[1].symbol))

    opened = []
    for _mfs, s in scored[:ccfg.SCAN_LIMIT]:
        d = council.decide(s)
        if not d["tradeable"]:
            book.journal(s.symbol, "rejected", d)
            continue
        size_usd, qty, violations = council.size_position(
            equity, cash, book.gross_exposure(), s.price,
            d["confidence"], d["opportunity"], s.realized_vol)
        if violations or qty <= 0:
            d["violations"] = d["violations"] + violations
            book.journal(s.symbol, "size_blocked", d)
            continue
        res = equity_order(s.symbol, qty, "buy")
        if res is not None and res.get("status") != "dry_run":
            book.open_position(symbol=s.symbol, qty=qty, entry_px=s.price, size_usd=size_usd,
                               opportunity=d["opportunity"], risk_score=d["risk"],
                               confidence=d["confidence"], client_order_id=res.get("client_order_id"))
            book.journal(s.symbol, "opened", d)
            opened.append(s.symbol)
        elif res is not None:
            # DRY_RUN: journal the decision, never write a position the
            # broker does not hold (2026-10-15: a dry cycle wrote a phantom
            # AAPL row that would have been "managed" and "sold" for real).
            book.journal(s.symbol, "dry_run_would_open", d)
            opened.append(f"{s.symbol}(dry)")
            cash -= size_usd
            if len(opened) >= budget:
                break
        else:
            book.journal(s.symbol, "order_failed", d)

    print(f"council: opened {opened or '-'} | scanned {len(scored)}", *notes)


if __name__ == "__main__":
    main()
