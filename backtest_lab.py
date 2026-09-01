"""Incremental backtest lab (PLAN D17 PR7) — "add a component, measure, repeat".

Runs the strategy over the available REAL daily-bar history (~16 months evaluated) and measures each layer's
contribution, cumulatively:

  L1  raw signals            every non-neutral signal becomes a trade
  L2  + trend filter         EMA50/200 + ADX regime gate
  L3  + volatility filter    ATR%-percentile gate (production event set)
  L4  selection policies on the SAME L3 candidates, per-day budget of 2:
        rule    highest strength first (the live shadow selector's spirit)
        random  uniform, matched to the rule's trade count, seeded
        claude  masked-Claude judgment (only with --with-llm)

HONESTY HEADER (printed with results, per PLAN D3/D5):
- Spread economics are Black-Scholes on a realized-vol proxy — NOT historical
  option chains (unavailable on the free plan). Results are RELATIVE
  comparisons between configs, never absolute performance claims.
- The Claude policy sees MASKED candidates (TICKER_A/B..., DTE only, no
  dates) — KTD-Fin-style leakage mitigation, since the model's weights have
  seen this period's market history. Still: treat as exploratory.
- No portfolio-level cap/margin simulation; per-spread cap only (inherited
  from simulate_trade). Execution/fills/microstructure are out of scope —
  the pre-trade gate is exercised by the chaos tests instead.

Signal scoring, filters, and trade simulation are REUSED from
backtest_optimize.py (Alex's frozen port), not forked. That module imports
trading_bot's HistoricalDataLoader at top level, which only exists on his
machine — a stub is injected so the import succeeds; this lab loads bars
itself via the repo's own AlpacaClient (cached under state/bars/).

Usage:
  set -a; source .env; set +a
  python backtest_lab.py             # L1-L4 with rule + random
  python backtest_lab.py --with-llm  # adds masked-Claude (~1 claude call/day, slow)
"""
from __future__ import annotations

import json
import random as _random
import sys
import types
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

# --- stub the trading_bot-only dependency so backtest_optimize imports ------
_stub = types.ModuleType("backtest.data")
_stub.HistoricalDataLoader = object  # never instantiated by this lab
_pkg = types.ModuleType("backtest")
_pkg.data = _stub
sys.modules.setdefault("backtest", _pkg)
sys.modules.setdefault("backtest.data", _stub)

import backtest_optimize as bo  # noqa: E402  (reused, not forked)
import black_scholes  # noqa: E402
from alpaca_client import AlpacaClient  # noqa: E402
from alpaca.data.timeframe import TimeFrame  # noqa: E402
from signals.adaptive import AdaptiveIndicators  # noqa: E402
from signals.trend_filter import TrendFilter  # noqa: E402

BARS_DIR = Path(__file__).resolve().parent / "state" / "bars"
LOOKBACK_DAYS = 400          # ~6 months of evaluated days after warmup
WARMUP = bo.WARMUP_TRADING_DAYS
PER_DAY_BUDGET = 2
PROD_PARAMS = dict(target_delta=0.17, dte_range=(10, 21), profit_target_pct=0.50)


def load_bars(symbols: list[str]) -> dict[str, pd.DataFrame]:
    BARS_DIR.mkdir(parents=True, exist_ok=True)
    client = AlpacaClient()
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=LOOKBACK_DAYS + 400)  # + warmup room
    out: dict[str, pd.DataFrame] = {}
    for sym in symbols:
        cache = BARS_DIR / f"{sym}.csv"
        if cache.exists():
            df = pd.read_csv(cache, index_col=0, parse_dates=True)
        else:
            bars = client.get_bars(sym, TimeFrame.Day, start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d"), limit=10000)
            df = pd.DataFrame(bars)
            if df.empty or "close" not in df.columns:
                print(f"  {sym}: no bars, skipped")
                continue
            ts_col = "timestamp" if "timestamp" in df.columns else df.columns[0]
            df[ts_col] = pd.to_datetime(df[ts_col])
            df = df.set_index(ts_col).sort_index()
            df.to_csv(cache)
        if len(df) > WARMUP + 30:
            out[sym] = df
    return out


def find_events(
    data: dict[str, pd.DataFrame], *, use_trend: bool, use_vol: bool,
    adx_gated_trend: bool = False,
) -> list[tuple]:
    """backtest_optimize.main's event loop, with the filters made toggleable.

    adx_gated_trend=True tests the 2026-09-01 hypothesis: only block
    counter-trend signals when ADX > 25 (same TrendFilter class live uses,
    so a lab win here transfers directly)."""
    adaptive = AdaptiveIndicators()
    trend_filter = TrendFilter(block_only_strong_trend=adx_gated_trend)
    events = []
    for symbol, df in data.items():
        cooldown_until = -1
        for i in range(WARMUP, len(df) - 3):
            if i <= cooldown_until:
                continue
            window = df.iloc[max(0, i - 89): i + 1]
            sig = bo._signal_from_df(symbol, window, adaptive)
            if sig is None or sig.direction == "neutral":
                continue
            trend_window = df.iloc[: i + 1]
            if use_trend:
                try:
                    if not trend_filter.check(trend_window, sig.direction).allowed:
                        continue
                except Exception:
                    pass
            if use_vol and not bo._passes_volatility_filter(trend_window):
                continue
            realized_vol = black_scholes.realized_vol_from_bars(trend_window)
            if realized_vol <= 0:
                continue
            spot = float(df["close"].iloc[i])
            events.append((symbol, i, sig.direction, sig.strength, spot, realized_vol, df))
            cooldown_until = i + 25
    return events


def simulate_events(events: list[tuple]) -> list:
    trades = []
    for symbol, i, direction, _strength, spot, rvol, df in events:
        t = bo.simulate_trade(df, i, direction, spot, rvol,
                              PROD_PARAMS["target_delta"], PROD_PARAMS["dte_range"],
                              PROD_PARAMS["profit_target_pct"])
        if t is not None:
            t.symbol = symbol
            trades.append(t)
    return trades


def metrics(trades: list) -> dict:
    if not trades:
        return {"n": 0, "total_pnl": 0.0, "win_rate": None, "avg": None, "max_drawdown": None}
    ordered = sorted(trades, key=lambda t: t.exit_date)
    pnls = [t.pnl for t in ordered]
    cum = peak = dd = 0.0
    for p in pnls:
        cum += p
        peak = max(peak, cum)
        dd = min(dd, cum - peak)
    wins = sum(1 for p in pnls if p > 0)
    return {
        "n": len(pnls),
        "total_pnl": round(sum(pnls), 2),
        "win_rate": round(wins / len(pnls), 3),
        "avg": round(sum(pnls) / len(pnls), 2),
        "max_drawdown": round(dd, 2),
    }


# --- L4: per-day selection policies on the production event set -------------

def by_day(events: list[tuple]) -> dict:
    days: dict = {}
    for ev in events:
        symbol, i, *_rest, df = ev
        day = df.index[i].date()
        days.setdefault(day, []).append(ev)
    return days


def policy_rule(day_events: list[tuple]) -> list[tuple]:
    """Match live selector.shadow_select: strength × (credit/max_loss)."""
    from selector import mechanical_score

    scored = []
    for ev in day_events:
        symbol, i, direction, strength, spot, rvol, df = ev
        dte0 = sum(PROD_PARAMS["dte_range"]) // 2
        option_type = "put" if direction == "long" else "call"
        short_k = bo.strike_for_delta(
            spot=spot, target_delta=PROD_PARAMS["target_delta"],
            dte_days=dte0, volatility=rvol, option_type=option_type,
        )
        long_k = short_k - bo.SPREAD_WIDTH if direction == "long" else short_k + bo.SPREAD_WIDTH
        credit = (
            bo.bs_price(spot=spot, strike=short_k, dte_days=dte0, volatility=rvol, option_type=option_type)
            - bo.bs_price(spot=spot, strike=long_k, dte_days=dte0, volatility=rvol, option_type=option_type)
        ) * 100
        max_loss = bo.SPREAD_WIDTH * 100 - credit
        score = mechanical_score({
            "strength": strength, "credit_estimate": credit, "max_loss": max_loss,
        })
        scored.append((score, ev))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [ev for _s, ev in scored[:PER_DAY_BUDGET]]


def policy_random(day_events: list[tuple], n: int, seed: int) -> list[tuple]:
    rng = _random.Random(seed)
    return rng.sample(day_events, min(n, len(day_events)))


def policy_claude(day_events: list[tuple], seed: int) -> list[tuple]:
    """Masked judgment: anonymized tickers, DTE only, no dates (leakage
    mitigation). Reuses the live reasoner's claude_code path."""
    import llm_reasoner

    labels = {}
    cands = []
    for idx, (symbol, i, direction, strength, spot, rvol, df) in enumerate(day_events):
        label = f"TICKER_{chr(65 + idx)}"
        labels[label] = day_events[idx]
        dte0 = sum(PROD_PARAMS["dte_range"]) // 2
        option_type = "put" if direction == "long" else "call"
        short_k = bo.strike_for_delta(spot=spot, target_delta=PROD_PARAMS["target_delta"],
                                      dte_days=dte0, volatility=rvol, option_type=option_type)
        long_k = short_k - bo.SPREAD_WIDTH if direction == "long" else short_k + bo.SPREAD_WIDTH
        credit = (bo.bs_price(spot=spot, strike=short_k, dte_days=dte0, volatility=rvol, option_type=option_type)
                  - bo.bs_price(spot=spot, strike=long_k, dte_days=dte0, volatility=rvol, option_type=option_type)) * 100
        cands.append({
            "ticker": label,
            "direction": "bull_put" if direction == "long" else "bear_call",
            "strength": strength,
            "signal_reasoning": "masked historical simulation — judge on the numbers only",
            "credit_estimate": round(credit, 2),
            "max_loss": round(bo.SPREAD_WIDTH * 100 - credit, 2),
            "expiration": f"DTE {dte0}",
        })
    out = llm_reasoner._decide_via_claude_code(cands, remaining_budget=PER_DAY_BUDGET)
    picked = [labels[t] for t in out.get("selected", []) if t in labels]
    return picked


def persist(all_trades: dict[str, list], results: dict) -> None:
    """Append a lab run (run_id) — never truncate prior experiments."""
    try:
        import db
        from datetime import datetime, timezone
        run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        with db._connection() as conn, conn.cursor() as cur:
            for config, trades in all_trades.items():
                for tr in sorted(trades, key=lambda x: x.entry_date):
                    cur.execute(
                        f"""insert into {db._schema()}.lab_trades
                            (run_id, config, symbol, direction, entry_date, exit_date, credit, pnl, exit_reason)
                            values (%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                        (run_id, config, tr.symbol, tr.direction, tr.entry_date.isoformat(),
                         tr.exit_date.isoformat(), round(tr.credit * 100, 2), round(tr.pnl, 2), tr.exit_reason),
                    )
                m = results.get(config)
                if isinstance(m, dict) and "n" in m:
                    cur.execute(
                        f"""insert into {db._schema()}.lab_summary
                            (run_id, config, n_trades, total_pnl, win_rate, avg_pnl, max_drawdown)
                            values (%s,%s,%s,%s,%s,%s,%s)""",
                        (run_id, config, m["n"], m["total_pnl"], m["win_rate"], m["avg"], m["max_drawdown"]),
                    )
        print(f"Per-trade history appended to Supabase (run_id={run_id}).")
    except Exception as exc:
        print(f"WARNING: could not persist lab trades to Supabase: {exc}")


def main() -> None:
    with_llm = "--with-llm" in sys.argv
    print(__doc__.split("HONESTY HEADER")[1].split("Signal scoring")[0])

    print("Loading bars (cached under state/bars/)...")
    data = load_bars(bo.BASKET)
    print(f"  {len(data)}/{len(bo.BASKET)} symbols usable\n")

    results = {}
    all_trades: dict[str, list] = {}

    ladder = [
        ("L1 raw signals", dict(use_trend=False, use_vol=False)),
        ("L2 + trend filter", dict(use_trend=True, use_vol=False)),
        ("L3 + vol filter", dict(use_trend=True, use_vol=True)),
        # ADX-gated trend variants (2026-09-01): counter-trend blocked only
        # when ADX > 25. Compare L2b vs L2 and L3b vs L3 — same window/seeds.
        ("L2b ADX-gated trend", dict(use_trend=True, use_vol=False, adx_gated_trend=True)),
        ("L3b ADX-gated + vol", dict(use_trend=True, use_vol=True, adx_gated_trend=True)),
    ]
    l3_events = None
    for name, toggles in ladder:
        events = find_events(data, **toggles)
        trades = simulate_events(events)
        results[name] = metrics(trades)
        all_trades[name] = trades
        if name == "L3 + vol filter":
            # Exact match: "L3b ADX-gated + vol" must NOT replace the L4
            # candidate set, or the policy baselines silently shift.
            l3_events = events
        print(f"{name:22s} events={len(events):4d}  {results[name]}")

    print("\nL4 selection policies (same L3 candidates, per-day budget "
          f"{PER_DAY_BUDGET}):")
    days = by_day(l3_events or [])
    rule_picks, claude_picks = [], []
    for day, evs in sorted(days.items()):
        rule_picks += policy_rule(evs)
        if with_llm:
            try:
                claude_picks += policy_claude(evs, seed=day.toordinal())
            except Exception as exc:
                print(f"  {day}: claude policy failed ({exc}) — skipping day")

    trades = simulate_events(rule_picks)
    results["L4 rule"] = metrics(trades)
    all_trades["L4 rule"] = trades
    print(f"L4 rule     picks={len(rule_picks):4d}  {results['L4 rule']}")

    # One random draw is noise ($984/$1269/$1129 across three seeds during
    # development) — evaluate the random policy as a DISTRIBUTION over 20
    # seeds and report mean/std; persist the median-seed draw's trades.
    random_totals = []
    median_trades = None
    for offset in range(20):
        picks = []
        for day, evs in sorted(days.items()):
            picks += policy_random(evs, len(policy_rule(evs)), seed=day.toordinal() + offset * 100_003)
        trs = simulate_events(picks)
        random_totals.append(round(sum(x.pnl for x in trs), 2))
        if offset == 0:
            median_trades = trs
    import statistics as _st
    results["L4 random(20 seeds)"] = {
        "n": len(median_trades or []),
        "total_pnl": round(_st.mean(random_totals), 2),
        "win_rate": None,
        "avg": None,
        "max_drawdown": None,
        "std": round(_st.stdev(random_totals), 2),
        "min": min(random_totals),
        "max": max(random_totals),
    }
    all_trades["L4 random(20 seeds)"] = median_trades or []
    print(f"L4 random   20 seeds: mean={_st.mean(random_totals):,.2f} std={_st.stdev(random_totals):,.2f} "
          f"min={min(random_totals):,.2f} max={max(random_totals):,.2f}")
    if with_llm:
        trades = simulate_events(claude_picks)
        results["L4 claude(masked)"] = metrics(trades)
        all_trades["L4 claude(masked)"] = trades
        print(f"L4 claude   picks={len(claude_picks):4d}  {results['L4 claude(masked)']}")

    spy = data.get("SPY")
    if spy is not None and len(spy) > WARMUP:
        window = spy["close"].iloc[WARMUP:]
        results["SPY_buy_hold_pct"] = round(float(window.iloc[-1] / window.iloc[0] - 1) * 100, 2)
        print(f"\nSPY buy & hold over the same evaluated window: {results['SPY_buy_hold_pct']}%")

    persist(all_trades, results)

    out_path = Path(__file__).resolve().parent / "state" / "backtest_results.json"
    out_path.write_text(json.dumps({"generated_at": datetime.now(timezone.utc).isoformat(),
                                    "params": {**PROD_PARAMS, "dte_range": list(PROD_PARAMS["dte_range"])},
                                    "results": results}, indent=2, default=str))
    print(f"\nResults written to {out_path}")


if __name__ == "__main__":
    main()
