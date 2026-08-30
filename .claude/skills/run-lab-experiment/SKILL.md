---
name: run-lab-experiment
description: Test a parameter/signal hypothesis offline in the backtest lab before changing live trading code. Use when evidence suggests a threshold/filter change but one day of live data can't justify it alone.
---

# Run a lab experiment

`backtest_lab.py` replays ~16 months of daily bars (cached in `state/bars/`)
through the component ladder. Use it to compare a proposed config against the
current one BEFORE editing live parameters.

## Procedure
1. State the hypothesis as a comparison: "config X beats current on total
   proxy P&L / drawdown / win rate over the same window."
2. Run the relevant ladder level with your variant (see `--help`; levels:
   L1 raw → L2 +trend → L3 +vol → L4 selector policies). Keep the same seeds
   and window as the baseline so the diff is the config, not the data.
3. Compare against `lab_summary` baselines (also in `evening_context.json`).
   A change must beat baseline on its target metric WITHOUT degrading max
   drawdown materially.
4. Persist results (`persist()` path → `lab_trades`/`lab_summary`) so the
   dashboard /lab page and future sessions see the run.
5. In NIGHTLY.md: hypothesis, numbers table, decision (adopt / reject /
   needs live evidence), and if adopted — the live edit + its prediction.

## Honesty caveats (repeat them in your review)
- Spread economics use a Black-Scholes/realized-vol proxy (no historical
  chains on the free feed): results are RELATIVE comparisons only, never
  absolute P&L claims.
- The lab can't see execution/fills/microstructure — those live in chaos
  tests and the real slippage column.
- Claude-in-backtest legs must stay masked (TICKER_A, DTE-only) per PLAN D3.
