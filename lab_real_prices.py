"""Real-price backtest layer (Roadmap v2 headline).

Replaces the lab's Black-Scholes proxy marks with REAL historical option
prices from Alpaca's /v1beta1/options/bars (daily bars, available since
Feb 2024 on the free plan), plus optopsy-style conservative fills and
first-threshold-crossing exits.

Honesty notes, printed by the revalidation runner:
- Daily bars are TRADE aggregates: sparse strikes have gaps; there is no
  historical bid/ask, so entry/exit fills apply an assumed half-spread
  (optopsy's 'spread' model) on top of bar closes — conservative.
- A contract with fewer than MIN_BARS observed bars over the trade window
  falls back to the Black-Scholes proxy and is COUNTED as a fallback, never
  silently mixed in.
"""
from __future__ import annotations

import json
import logging
import os
from datetime import date, timedelta
from pathlib import Path

import requests

logger = logging.getLogger(__name__)

DATA_URL = "https://data.alpaca.markets/v1beta1/options/bars"
CACHE_DIR = Path(__file__).resolve().parent / "state" / "option_bars"
MIN_BARS = 3  # fewer observed bars than this across the window -> fallback


# ---------- pure helpers (offline-testable) ----------------------------------

def occ_symbol(underlying: str, expiration: date, right: str, strike: float) -> str:
    """OCC option symbol, e.g. QQQ260914C00725000."""
    assert right in ("C", "P")
    return (
        f"{underlying.upper()}{expiration.strftime('%y%m%d')}{right}"
        f"{int(round(strike * 1000)):08d}"
    )


def snap_strike(strike: float, increment: float = 1.0) -> float:
    return round(round(strike / increment) * increment, 2)


def snap_to_friday(d: date) -> date:
    """Nearest Friday at or after d (weekly index-ETF expiries)."""
    return d + timedelta(days=(4 - d.weekday()) % 7)


def entry_credit(short_close: float, long_close: float, half_spread_pct: float = 0.05,
                 min_half_spread: float = 0.02) -> float:
    """Conservative credit: sell the short below its close, buy the long
    above its close (optopsy 'spread' slippage model on bar closes)."""
    hs_s = max(min_half_spread, short_close * half_spread_pct)
    hs_l = max(min_half_spread, long_close * half_spread_pct)
    return (short_close - hs_s) - (long_close + hs_l)


def exit_debit(short_close: float, long_close: float, half_spread_pct: float = 0.05,
               min_half_spread: float = 0.02) -> float:
    """Conservative cost to close: buy short back above close, sell long below."""
    hs_s = max(min_half_spread, short_close * half_spread_pct)
    hs_l = max(min_half_spread, long_close * half_spread_pct)
    return (short_close + hs_s) - (long_close - hs_l)


def simulate_real_spread(
    short_bars: dict[str, float],
    long_bars: dict[str, float],
    entry_day: str,
    expiration: date,
    *,
    profit_target_pct: float = 0.50,
    stop_loss_multiple: float = 2.0,
    half_spread_pct: float = 0.05,
) -> dict | None:
    """Walk shared post-entry dates on real closes; first threshold crossing
    wins (mirrors risk_gate.should_close semantics). Returns
    {pnl, exit_reason, exit_date, credit, n_marks} in dollars/contract,
    or None if the entry day isn't quoted on both legs."""
    if entry_day not in short_bars or entry_day not in long_bars:
        return None
    credit = entry_credit(short_bars[entry_day], long_bars[entry_day], half_spread_pct) * 100
    if credit <= 0:
        return None

    days = sorted(set(short_bars) & set(long_bars))
    marks = [(d, exit_debit(short_bars[d], long_bars[d], half_spread_pct) * 100)
             for d in days if d > entry_day]
    for d, mark in marks:
        captured = 1 - (mark / credit) if credit else 0.0
        if captured >= profit_target_pct:
            return {"pnl": credit - mark, "exit_reason": "profit_target",
                    "exit_date": d, "credit": credit, "n_marks": len(marks)}
        if mark >= credit * stop_loss_multiple:
            return {"pnl": credit - mark, "exit_reason": "stop",
                    "exit_date": d, "credit": credit, "n_marks": len(marks)}
        if date.fromisoformat(d) >= expiration - timedelta(days=1):
            return {"pnl": credit - mark, "exit_reason": "expiry",
                    "exit_date": d, "credit": credit, "n_marks": len(marks)}
    if marks:  # data ends before any threshold: mark-to-last (counted as such)
        d, mark = marks[-1]
        return {"pnl": credit - mark, "exit_reason": "data_end",
                "exit_date": d, "credit": credit, "n_marks": len(marks)}
    return None


# ---------- data access (network; cached) -------------------------------------

def _headers() -> dict:
    return {"APCA-API-KEY-ID": os.environ["ALPACA_API_KEY"],
            "APCA-API-SECRET-KEY": os.environ["ALPACA_SECRET_KEY"]}


def fetch_daily_closes(symbols: list[str], start: str, end: str) -> dict[str, dict[str, float]]:
    """{occ_symbol: {YYYY-MM-DD: close}} from Alpaca historical option bars.
    Per-symbol JSON cache under state/option_bars/. <=100 symbols/request."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    out: dict[str, dict[str, float]] = {}
    missing: list[str] = []
    for s in symbols:
        cache = CACHE_DIR / f"{s}_{start}_{end}.json"
        if cache.exists():
            out[s] = json.loads(cache.read_text())
        else:
            missing.append(s)

    for i in range(0, len(missing), 100):
        batch = missing[i:i + 100]
        params = {"symbols": ",".join(batch), "timeframe": "1Day",
                  "start": start, "end": end, "limit": 10000}
        bars_acc: dict[str, dict[str, float]] = {s: {} for s in batch}
        while True:
            resp = requests.get(DATA_URL, headers=_headers(), params=params, timeout=30)
            resp.raise_for_status()
            payload = resp.json()
            for sym, bars in (payload.get("bars") or {}).items():
                for b in bars:
                    bars_acc.setdefault(sym, {})[b["t"][:10]] = float(b["c"])
            token = payload.get("next_page_token")
            if not token:
                break
            params["page_token"] = token
        for sym in batch:
            (CACHE_DIR / f"{sym}_{start}_{end}.json").write_text(json.dumps(bars_acc.get(sym, {})))
            out[sym] = bars_acc.get(sym, {})
    return out
