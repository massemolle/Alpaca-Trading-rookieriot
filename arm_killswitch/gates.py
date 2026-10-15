"""The 15-gate ladder, re-implemented. Their stated invariants, kept:
gates may REJECT or SHRINK, never enlarge or invent; EXITS ARE NEVER GATED;
the killswitch halts entries only."""
from __future__ import annotations

from dataclasses import dataclass

from arm_killswitch import book, config as kcfg


@dataclass
class GateResult:
    allowed: bool
    reasons: list[str]
    contracts: int = 0


def pre_model_gates(equity: float, daily_pl: float) -> GateResult:
    """Free gates that run BEFORE any model call (their design: never pay
    for a decision you cannot act on)."""
    reasons = []
    if kcfg.TRADING_HALTED:
        reasons.append("killswitch: TRADING_HALTED (entries only; exits unaffected)")
    positions = book.open_positions()
    if len(positions) >= kcfg.MAX_POSITIONS:
        reasons.append(f"max positions {kcfg.MAX_POSITIONS}")
    if equity > 0 and daily_pl / equity <= -0.02:
        reasons.append("daily loss 2% of equity")
    return GateResult(not reasons, reasons)


def order_gates(ticker: str, right: str, premium: float, equity: float,
                price_ratio: float, theta_per_day: float, delta: float) -> GateResult:
    """Post-model gates on the concrete contract."""
    reasons = []
    positions = book.open_positions()
    group = kcfg.group_of(ticker)
    if sum(1 for p in positions if kcfg.group_of(p["underlying"]) == group) >= kcfg.MAX_PER_GROUP:
        reasons.append(f"max {kcfg.MAX_PER_GROUP} positions in correlation group '{group}'")
    if sum(1 for p in positions if p["right_"] == right) >= kcfg.MAX_SAME_DIRECTION:
        reasons.append(f"max {kcfg.MAX_SAME_DIRECTION} same-direction positions")
    if any(p["underlying"] == ticker for p in positions):
        reasons.append(f"already holding {ticker}")
    if not (kcfg.MIN_DELTA <= abs(delta) <= kcfg.MAX_DELTA):
        reasons.append(f"delta {abs(delta):.2f} outside [{kcfg.MIN_DELTA}, {kcfg.MAX_DELTA}]")
    if price_ratio > kcfg.RICHNESS_CAP:
        reasons.append(f"premium rich: {price_ratio:.2f}x fair > {kcfg.RICHNESS_CAP}")
    if premium > 0 and theta_per_day / premium > kcfg.MAX_THETA_BURDEN_PCT:
        reasons.append(f"theta burden {theta_per_day / premium:.2%}/day > {kcfg.MAX_THETA_BURDEN_PCT:.2%}")
    # Sizing: 4% of equity, shrink-to-fit (never enlarge).
    budget = equity * kcfg.EQUITY_PCT_PER_TRADE
    contracts = int(budget // premium) if premium > 0 else 0
    if contracts < 1:
        reasons.append(f"premium ${premium:.0f} exceeds {kcfg.EQUITY_PCT_PER_TRADE:.0%} equity budget ${budget:.0f}")
    return GateResult(not reasons, reasons, contracts=max(contracts, 0))


def exit_decision(entry_premium: float, current_premium: float, spot: float,
                  stop_spot: float, right: str, dte: int) -> str | None:
    """Their exit ladder. Pure function — exits are never gated."""
    if dte <= kcfg.FORCE_CLOSE_DTE:
        return "dte_force_close"
    if right == "call" and spot <= stop_spot:
        return "atr_stop"
    if right == "put" and spot >= stop_spot:
        return "atr_stop"
    if entry_premium > 0:
        if current_premium <= entry_premium * kcfg.PREMIUM_FLOOR_PCT:
            return "premium_floor"
        if current_premium >= entry_premium * (1 + kcfg.TAKE_PROFIT_PCT):
            return "take_profit"
    return None
