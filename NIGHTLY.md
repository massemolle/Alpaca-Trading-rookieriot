# Nightly engineer log

One dated entry per evening session — what the evidence showed, what changed, what to watch. Written by the Fable engineer (see prompts/evening_engineer.md); kept only when the verification gate passes.

## 2026-09-01 (reviewing trading day 2026-08-31 — day 1)

**Evidence.** Ablation and regret were both empty: zero candidates reached the
gate or the LLM all day, so no book traded (the only positions are the two
operator-ordered manual experiments, SPY/QQQ bull puts). Per the analyze-regret
procedure: no pattern, judge unexaminable — the weak link is upstream of the
menu. Tracing the funnel in `state/bot.log`:

- Screening passed **0–1 of 3** universe tickers every cycle
  ("Screening: 1 / 3"), reasons visible only at DEBUG (i.e., lost).
- The 0–1 surviving signals then died in the trend/vol filters **silently** —
  a trend-filter block was a bare `continue` with no log and no journal entry.
- Root cause of the screening drop: `ScreeningFilters.max_price = 300`, carried
  over verbatim from the stock bot's share-affordability screen. SPY closed at
  767.17 and QQQ at 716.69 — **structurally excluded** from the ETF universe
  the whole system was designed around. Only IWM (293.89, six dollars under
  the cap) could ever reach signal generation. The backtest lab that validated
  the L3/L4 pipeline uses a hardcoded basket (SPY, MSFT, META, …) and bypasses
  screening entirely, so live trading could never reproduce the validated
  configuration.

**Changes.**
1. `config.py`: screening `max_price` default 300 → 1000 (env `MAX_PRICE`
   still overrides; `.env` does not set it). This is not a risk-limit change:
   underlying share price is not a risk axis for defined-risk verticals —
   affordability/risk is enforced downstream by max-loss sizing (contracts<1
   rejects) and both gates, none of which changed. It aligns live screening
   with the universe decision (SPY/QQQ/IWM) and with the basket the lab's
   profitable configs actually traded. No lab run can test this parameter —
   the lab bypasses screening.
2. Funnel observability: `filter_universe` now reports per-ticker rejection
   reasons (`rejections_out`), `bot._apply_trend_and_volatility_filters`
   returns `(kept, rejections)` and logs trend blocks, spread-builder failures
   are journaled, and all pre-menu rejections flow into the decision journal's
   `gate_rejections` with a `stage` tag (screening / trend_filter / vol_filter /
   spread_builder / sizing / risk_gate). Empty-menu days are now attributable
   at evening review instead of requiring log archaeology.
3. New `tests/test_funnel_observability.py` (6 tests) pins the max_price fix
   (SPY/QQQ price levels must pass) and every rejection-reporting path.

**Deliberately NOT changed.** The realized-vol floor (0.40, relax to 0.25)
rejected the IWM signals that did get through — defensible in a 1st-percentile
RV regime, the lab shows the vol filter is the main profitability driver
(L2→L3: −$1,069 → +$1,289), and one quiet day is not evidence. Left alone.

**Watch tomorrow.**
- With SPY/QQQ visible, expect the menu to populate; the journal will now show
  exactly which stage eats what. If trend/vol still empties the menu on SPY/QQQ,
  *that* becomes the evidence for a lab experiment on the vol floor — design it
  from the journaled percentile values, don't guess.
- The two manual positions (SPY 756/751, QQQ 697/692, exp 2026-09-10) are
  managed by the normal exit path; small mark-to-market noise so far (−$4 EOD).
- Broad-universe note: screening rejections now log at INFO per ticker; fine
  for the 3-ETF live universe, chatty if anyone runs UNIVERSE_MODE=broad
  online (offline experiments unaffected in spirit).
