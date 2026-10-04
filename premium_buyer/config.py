"""Premium-buyer sleeve config (Roadmap "podium lessons", 2026-10-04).

Long premium, short leash — mechanics adapted from the hackathon champion
Autobelay (MIT, (c) 2026 W.P. & W.C. McCormick) re-implemented in this
project's style. Runs in PARALLEL with the credit-spread bot: own book,
own cron, own caps; shares the account, the MCP plumbing and the doctrine
(model proposes with cited facts, code disposes, abstention default).
"""
from __future__ import annotations

import os


def _f(n, d):
    v = os.environ.get(n)
    return float(v) if v is not None else d


def _i(n, d):
    v = os.environ.get(n)
    return int(v) if v is not None else d


UNIVERSE = [t.strip().upper() for t in os.environ.get("PREMIUM_UNIVERSE", "SPY,QQQ,NVDA").split(",") if t.strip()]
MAX_PREMIUM_PER_POSITION = _f("PREMIUM_MAX_PER_POSITION", 500.0)   # $ paid, hard cap
MAX_POSITIONS = _i("PREMIUM_MAX_POSITIONS", 4)
STOP_PCT = _f("PREMIUM_STOP_PCT", 0.40)          # exit at -40% of premium
TAKE_PCT = _f("PREMIUM_TAKE_PCT", 0.60)          # exit at +60%
DAILY_LOSS_HALT = _f("PREMIUM_DAILY_LOSS_HALT", 1000.0)
MIN_DTE = _i("PREMIUM_MIN_DTE", 5)               # avoid 0-2 DTE gamma lottos
MAX_DTE = _i("PREMIUM_MAX_DTE", 14)
TARGET_DELTA = _f("PREMIUM_TARGET_DELTA", 0.40)  # ~ATM-lite, champion's zone
# Killswitch-derived richness gate, buyer's direction: only BUY premium that
# prices <= RICHNESS_CAP x its Black-Scholes value at realized vol.
RICHNESS_CAP = _f("PREMIUM_RICHNESS_CAP", 1.40)
ENTRY_START_UTC = os.environ.get("PREMIUM_ENTRY_START", "13:45")   # 09:45 ET
ENTRY_END_UTC = os.environ.get("PREMIUM_ENTRY_END", "19:15")       # 15:15 ET
MIN_STATED_P = _f("PREMIUM_MIN_STATED_P", 0.55)  # model's own p(favorable move)
MOVE_THRESHOLD_PCT = _f("PREMIUM_MOVE_THRESHOLD", 1.0)  # % move defining Brier outcome
# Independent of the credit bot's DRY_RUN so a brand-new strategy never
# auto-trades before a live rehearsal. Defaults DRY even when the account
# is otherwise live; flip PREMIUM_DRY_RUN=false after a clean dry cycle.
DRY_RUN = os.environ.get("PREMIUM_DRY_RUN", "true").lower() == "true"
