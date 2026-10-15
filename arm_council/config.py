"""ARM 4 — "Should-AI Buy?" replication (2nd place, SquadBlessingMiracle).

Source: github.com/nabielnovelkhubran/Should-AI-Buy (Business Source
License 1.1 — its Additional Use Grant explicitly permits non-commercial,
personal, research and TESTING use "including executing paper trading in
non-production sandbox environments", which is exactly this. Full licence
text vendored at arm_council/LICENSE-SHOULD-AI-BUY.txt as the licence
requires.) Re-implemented in Python from a line-level spec of their
TypeScript; their stack is a Next.js app and cannot be run as a cron sleeve.

TWO FACTS ABOUT THE ORIGINAL, PRESERVED HONESTLY:
1. It trades LONG US EQUITIES (and crypto spot) — never options. Its
   contract selector exists but is dead code, never reaching order
   submission. This arm therefore trades equities, like theirs.
2. Its 7-stage council is 100% DETERMINISTIC — no LLM in the authoritative
   path. The single optional LLM call can only DOWNGRADE a BUY, never
   create or elevate one. Kept exactly so: this is our control arm, the
   one sleeve with no model making decisions.

Operator twist (2026-10-15): parameters shifted LONGER-TERM — exits
widened (drawdown -5% -> -8%, profit target +4/5% -> +10%), momentum
reversal relaxed (40 -> 30), holding bias increased.
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
    "COUNCIL_UNIVERSE", "AAPL,NVDA,MSFT,AMZN,GOOGL,META,TSLA,AMD,COIN").split(",") if t.strip()]

# --- their STANDARD profile, verbatim --------------------------------------
MAX_POSITION_SIZE_USD = _f("COUNCIL_MAX_POS_USD", 5000.0)
MAX_PORTFOLIO_EXPOSURE_PCT = _f("COUNCIL_MAX_EXPOSURE_PCT", 50.0)
MAX_CONCENTRATION_PCT = _f("COUNCIL_MAX_CONC_PCT", 25.0)
MIN_CONFIDENCE = _i("COUNCIL_MIN_CONFIDENCE", 65)
MIN_OPPORTUNITY = _i("COUNCIL_MIN_OPPORTUNITY", 60)
CANDIDATE_FLOOR = _i("COUNCIL_CANDIDATE_FLOOR", 55)
MIN_RR = _f("COUNCIL_MIN_RR", 2.0)
MIN_LIQUIDITY_USD = _f("COUNCIL_MIN_LIQUIDITY", 500_000.0)
MAX_SPREAD_BPS = _f("COUNCIL_MAX_SPREAD_BPS", 50.0)
MAX_OPEN_POSITIONS = _i("COUNCIL_MAX_POSITIONS", 5)
SCAN_LIMIT = _i("COUNCIL_SCAN_LIMIT", 5)
# risk gate
GATE_MIN_LIQUIDITY = _f("COUNCIL_GATE_MIN_LIQ", 250_000.0)
GATE_MAX_RISK_SCORE = _f("COUNCIL_GATE_MAX_RISK", 70.0)
GATE_MIN_OPPORTUNITY = _f("COUNCIL_GATE_MIN_OPP", 60.0)
GATE_MAX_ALLOC_PCT = _f("COUNCIL_GATE_MAX_ALLOC", 25.0)
GATE_MIN_EVIDENCE = _i("COUNCIL_GATE_MIN_EVIDENCE", 3)

# --- exits: THE LONGER-TERM TWIST ------------------------------------------
EXIT_DRAWDOWN_PCT = _f("COUNCIL_EXIT_DRAWDOWN", -8.0)      # theirs: -5.0
EXIT_PROFIT_PCT = _f("COUNCIL_EXIT_PROFIT", 10.0)          # theirs: 4.0/5.0
EXIT_MOMENTUM_MIN = _f("COUNCIL_EXIT_MOMENTUM_MIN", 30.0)  # theirs: 40
EXIT_RSI_EXHAUSTION = _f("COUNCIL_EXIT_RSI", 78.0)
EXIT_MOMENTUM_EXHAUSTION = _f("COUNCIL_EXIT_MOM_EXH", 50.0)
EXIT_LIQUIDITY_MIN = _f("COUNCIL_EXIT_LIQ_MIN", 200_000.0)
EXIT_RISK_MAX = _f("COUNCIL_EXIT_RISK_MAX", 75.0)
VOLATILITY_SURGE_WARN = _f("COUNCIL_VOL_SURGE", 55.0)

DRY_RUN = os.environ.get("COUNCIL_DRY_RUN", "true").lower() == "true"
