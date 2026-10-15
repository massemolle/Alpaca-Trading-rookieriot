"""Deterministic scoring — their formulas, transcribed exactly.
Pure functions only: every number here is unit-testable offline."""
from __future__ import annotations

from dataclasses import dataclass


def clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


@dataclass
class Snapshot:
    """One immutable market picture per symbol per cycle (their MarketSnapshot)."""
    symbol: str
    price: float
    change24h: float
    rsi14: float
    rvol: float                 # relative volume vs average
    volume_accel: float         # % change in volume momentum
    realized_vol: float         # annualized %, e.g. 22.0
    liquidity_usd: float        # dollar volume
    spread_bps: float
    momentum: float             # 0-100


# ---- regime (regime.ts:40-76) ----------------------------------------------

def classify_regime(s: Snapshot) -> str:
    vol_high, vol_low = s.realized_vol > 45, s.realized_vol < 15
    bullish = s.rsi14 > 55 and s.momentum > 60
    bearish = s.rsi14 < 45 and s.momentum < 40
    if vol_high and bearish:
        return "RISK_OFF"
    if bullish and s.rvol >= 1.2 and s.volume_accel > 0:
        return "RISK_ON"
    if bullish:
        return "TRENDING_UP"
    if bearish:
        return "TRENDING_DOWN"
    if vol_high:
        return "HIGH_VOLATILITY"
    if vol_low and s.rvol < 0.9:
        return "LOW_VOLATILITY"
    return "RANGE_BOUND"


COMPATIBLE_REGIMES = {"RISK_ON", "TRENDING_UP", "RANGE_BOUND", "LOW_VOLATILITY"}


# ---- multi-factor score (strategy.ts:60-208) --------------------------------

def trend_score(rsi: float) -> float:
    if 50 <= rsi <= 70:
        return 80.0
    if rsi > 70:
        return 65.0
    if rsi < 40:
        return 30.0
    return 50.0


def volume_score(rvol: float, vol_accel: float) -> float:
    return 0.6 * min(100.0, rvol * 40) + 0.4 * clamp((vol_accel + 30) * 1.5, 0, 100)


def volatility_score(v: float) -> float:
    if 15 <= v <= 35:
        return 90.0
    if v <= 50:
        return 70.0
    return 40.0


def liquidity_score(liq: float, spread_bps: float) -> float:
    if liq >= 5_000_000 and spread_bps <= 10:
        return 95.0
    if liq >= 1_000_000 and spread_bps <= 25:
        return 80.0
    if liq >= 100_000 and spread_bps <= 50:
        return 65.0
    return 30.0


def estimated_rr(momentum: float, realized_vol: float) -> float:
    return max(1.0, max(3.0, momentum / 10 * 0.9) / clamp(realized_vol * 0.12, 1.5, 6.0))


def rr_score(rr: float) -> float:
    if rr >= 3.0:
        return 95.0
    if rr >= 2.0:
        return 75.0
    return 30.0


def multi_factor_score(s: Snapshot) -> tuple[float, dict]:
    regime = classify_regime(s)
    rr = estimated_rr(s.momentum, s.realized_vol)
    parts = {
        "momentum": s.momentum,
        "trend": trend_score(s.rsi14),
        "volume": volume_score(s.rvol, s.volume_accel),
        "volatility": volatility_score(s.realized_vol),
        "liquidity": liquidity_score(s.liquidity_usd, s.spread_bps),
        "catalyst": 70.0,                      # their constant
        "riskReward": rr_score(rr),
        "regimeCompatibility": 90.0 if regime in COMPATIBLE_REGIMES else 20.0,
    }
    weights = {"momentum": .20, "trend": .15, "volume": .15, "volatility": .10,
               "liquidity": .10, "catalyst": .10, "riskReward": .10,
               "regimeCompatibility": .10}
    score = sum(parts[k] * weights[k] for k in weights)
    return round(score, 2), {"regime": regime, "rr": round(rr, 2), "parts": parts}


# ---- opportunity + composite risk (quant/index.ts, risk/index.ts) -----------

def opportunity_score(s: Snapshot) -> float:
    return round(
        0.35 * s.momentum
        + 0.30 * clamp((s.volume_accel + 20) * 1.5, 0, 100)
        + 0.20 * clamp(s.rvol * 30, 0, 100)
        + 0.15 * clamp(s.liquidity_usd / 2_000_000 * 100, 0, 100), 2)


def composite_risk(s: Snapshot, concentration_pct: float = 20.0) -> float:
    conc = 95.0 if concentration_pct > 80 else 70.0 if concentration_pct > 60 \
        else 40.0 if concentration_pct > 40 else 15.0
    if s.liquidity_usd < 300_000:
        liq = 90.0
    elif s.liquidity_usd and s.rvol and s.liquidity_usd / max(s.liquidity_usd * s.rvol, 1) < 0.2:
        liq = 75.0
    elif s.liquidity_usd < 1_000_000:
        liq = 45.0
    else:
        liq = 15.0
    anomaly = 70.0 if s.realized_vol > 60 else 30.0
    unlock = 20.0
    return round(0.40 * conc + 0.25 * liq + 0.20 * anomaly + 0.15 * unlock, 2)
