"""ARM 3 — "Killswitch Capital" replication (3rd place, Team Quantus).

Their repo (github.com/SamsonDoski/alpaca-trading-assistant) went private
after the contest, so this is a faithful re-implementation from our
code-level review of it (2026-10-03), not a copy. Documented strategy:

  slightly-ITM single-leg long calls/puts, delta 0.55-0.75, 30-45 DTE,
  4% equity per trade, max 5 positions, max 3 per correlation group,
  ATR-keyed underlying stop (2.0x), 25% premium floor, 50% premium
  take-profit, force close at 7 DTE, IV/RV richness cap 1.4x, theta
  burden <= 1.5%/day, manual killswitch halting ENTRIES only.

Operator twist (2026-10-15): parameters shifted LONGER-TERM — their DTE
window already was 30-45 (the longest of the podium); we keep it and push
the force-close to 10 DTE so winners get more runway, and relax the ATR
stop slightly. Everything else is as specified.
"""
from __future__ import annotations

import os


def _f(n, d):
    v = os.environ.get(n)
    return float(v) if v is not None else d


def _i(n, d):
    v = os.environ.get(n)
    return int(v) if v is not None else d


UNIVERSE = [t.strip().upper() for t in os.environ.get(
    "KS_UNIVERSE", "IWM,SPY,TLT,QQQ,GLD,DIA,SLV,NVDA").split(",") if t.strip()]
EQUITY_PCT_PER_TRADE = _f("KS_EQUITY_PCT", 0.04)       # 4% of equity per trade
MAX_POSITIONS = _i("KS_MAX_POSITIONS", 5)
MAX_PER_GROUP = _i("KS_MAX_PER_GROUP", 3)              # correlation-group cap
MAX_SAME_DIRECTION = _i("KS_MAX_SAME_DIR", 5)
MIN_DELTA = _f("KS_MIN_DELTA", 0.55)                   # slightly ITM
MAX_DELTA = _f("KS_MAX_DELTA", 0.75)
MIN_DTE = _i("KS_MIN_DTE", 30)
MAX_DTE = _i("KS_MAX_DTE", 45)
ATR_STOP_MULT = _f("KS_ATR_STOP_MULT", 2.5)            # twist: 2.0 -> 2.5 (longer leash)
PREMIUM_FLOOR_PCT = _f("KS_PREMIUM_FLOOR_PCT", 0.25)   # exit if premium <= 25% of paid
TAKE_PROFIT_PCT = _f("KS_TAKE_PROFIT_PCT", 0.50)       # +50% premium
FORCE_CLOSE_DTE = _i("KS_FORCE_CLOSE_DTE", 10)         # twist: 7 -> 10 (longer-term)
RICHNESS_CAP = _f("KS_RICHNESS_CAP", 1.40)             # IV/RV: don't overpay
MAX_THETA_BURDEN_PCT = _f("KS_MAX_THETA_PCT", 0.015)   # <=1.5%/day of premium
TRADING_HALTED = os.environ.get("KS_TRADING_HALTED", "false").lower() == "true"
DRY_RUN = os.environ.get("KS_DRY_RUN", "true").lower() == "true"

# Correlation groups (their "max 3 per group" rule needs group membership).
GROUPS = {
    "equity_index": {"SPY", "QQQ", "DIA", "IWM"},
    "metals": {"GLD", "SLV"},
    "bonds": {"TLT"},
    "single_names": {"NVDA"},
}


def group_of(ticker: str) -> str:
    for g, members in GROUPS.items():
        if ticker in members:
            return g
    return "ungrouped"
