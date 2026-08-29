"""Dress rehearsal — run the REAL decision pipeline on Friday's real data,
while the market is closed, and see the result on the real dashboard.

What it exercises for real: signal scoring on actual bars, spread math,
fact provenance, the REAL Claude reasoner (unmasked, with facts), the
mechanical shadow selector, cycle + decision-journal persistence → visible
under "Recent agent decisions" on the dashboard within one refresh.

What it deliberately does NOT touch: orders (no MCP), the spreads table,
the shadow book — the real/virtual books stay clean. Rows are labeled
decision='rehearsal' and removable with:  python rehearsal.py --cleanup

Usage:  set -a; source .env; set +a; python rehearsal.py [--cleanup]
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone

import backtest_lab as lab
import backtest_optimize as bo
import black_scholes
import db
import llm_reasoner


def cleanup() -> None:
    with db._connection() as conn, conn.cursor() as cur:
        cur.execute(f"select id from {db._schema()}.cycles where decision='rehearsal'")
        ids = [r[0] for r in cur.fetchall()]
        if ids:
            cur.execute(f"delete from {db._schema()}.decision_journal where cycle_id = any(%s)", (ids,))
            cur.execute(f"delete from {db._schema()}.cycles where id = any(%s)", (ids,))
    print(f"removed {len(ids)} rehearsal cycle(s) and their journal rows")


def build_candidates() -> list[dict]:
    """Latest bar of each basket symbol → signal → spread plan numbers,
    using the same frozen scoring and BS math as the lab. Facts included,
    exactly like the live path."""
    from signals.adaptive import AdaptiveIndicators

    data = lab.load_bars(bo.BASKET)
    adaptive = AdaptiveIndicators()
    trend_filter = lab.TrendFilter()
    as_of = datetime.now(timezone.utc).isoformat()
    out = []
    for symbol, df in data.items():
        window = df.iloc[-90:]
        sig = bo._signal_from_df(symbol, window, adaptive)
        if sig is None or sig.direction == "neutral" or sig.strength < 0.3:
            continue
        try:
            if not trend_filter.check(df, sig.direction).allowed:
                continue
        except Exception:
            pass
        if not bo._passes_volatility_filter(df):
            continue
        rvol = black_scholes.realized_vol_from_bars(df)
        if rvol <= 0:
            continue
        spot = float(df["close"].iloc[-1])
        dte0 = 15
        option_type = "put" if sig.direction == "long" else "call"
        short_k = bo.strike_for_delta(spot=spot, target_delta=0.17, dte_days=dte0,
                                      volatility=rvol, option_type=option_type)
        long_k = short_k - bo.SPREAD_WIDTH if sig.direction == "long" else short_k + bo.SPREAD_WIDTH
        credit = (bo.bs_price(spot=spot, strike=short_k, dte_days=dte0, volatility=rvol, option_type=option_type)
                  - bo.bs_price(spot=spot, strike=long_k, dte_days=dte0, volatility=rvol, option_type=option_type)) * 100
        if credit <= 0:
            continue
        max_loss = bo.SPREAD_WIDTH * 100 - credit
        expiry = (datetime.now(timezone.utc) + timedelta(days=dte0)).date().isoformat()
        out.append({
            "ticker": symbol,
            "direction": "bull_put" if sig.direction == "long" else "bear_call",
            "strength": sig.strength,
            "signal_reasoning": "REHEARSAL on Friday's close — same scoring as live",
            "credit_estimate": round(credit, 2),
            "max_loss": round(max_loss, 2),
            "expiration": expiry,
            "facts": [
                {"fact_id": f"{symbol}_SIGNAL_STRENGTH", "value": sig.strength, "as_of": as_of,
                 "source": "signals.swing(frozen)", "quality": "computed", "derivation": None},
                {"fact_id": f"{symbol}_REALIZED_VOL", "value": round(rvol, 4), "as_of": as_of,
                 "source": "signals.indicators", "quality": "computed",
                 "derivation": "20d ATR% annualized — IV proxy"},
                {"fact_id": f"{symbol}_SPOT_CLOSE", "value": round(spot, 2), "as_of": as_of,
                 "source": "alpaca_daily_bars", "quality": "friday_close", "derivation": None},
                {"fact_id": f"{symbol}_CREDIT_EST", "value": round(credit, 2), "as_of": as_of,
                 "source": "black_scholes_proxy", "quality": "simulated",
                 "derivation": "BS on rv-proxy — market closed, no live quotes"},
                {"fact_id": f"{symbol}_MAX_LOSS", "value": round(max_loss, 2), "as_of": as_of,
                 "source": "computed", "quality": "computed", "derivation": "width x 100 - credit"},
                {"fact_id": f"{symbol}_DTE", "value": dte0, "as_of": as_of,
                 "source": "computed", "quality": "computed", "derivation": "fixed 15 for rehearsal"},
            ],
        })
    return out


def main() -> None:
    if "--cleanup" in sys.argv:
        cleanup()
        return

    import bot  # for _shadow_select (imports are side-effect-light offline)

    print("Building candidates from Friday's real bars...")
    candidates = build_candidates()
    print(f"{len(candidates)} candidates: {[c['ticker'] for c in candidates]}")
    if not candidates:
        print("No candidates today — rerun after refreshing bars (delete state/bars).")
        return

    print("Asking the REAL reasoner (this is a live Claude call)...")
    outcome = llm_reasoner.decide(candidates, remaining_budget=2)
    shadow = bot._shadow_select(candidates, remaining_budget=2)

    cycle_id = db.record_cycle(candidates, "rehearsal", outcome["reasoning"])
    db.record_decision_journal(
        cycle_id=cycle_id,
        candidates=candidates,
        llm_selected=outcome["selected"],
        llm_reasoning=outcome["reasoning"],
        shadow_selected=shadow,
        gate_rejections=[],
        pre_trade_rejections=[{"ticker": "-", "reasons": ["REHEARSAL — no orders placed, books untouched"], "facts": {}}],
    )
    print(f"\ncycle {cycle_id} recorded (decision='rehearsal')")
    print(f"Claude selected: {outcome['selected']}  |  mechanical rule: {shadow}")
    print(f"\nReasoning:\n{outcome['reasoning']}")
    print("\n→ open the dashboard: this decision is now in 'Recent agent decisions'.")
    print("→ remove with: python rehearsal.py --cleanup")


if __name__ == "__main__":
    main()
