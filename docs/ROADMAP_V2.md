# Roadmap v2 — from hackathon entry to a system worth funding

*Synthesized 2026-09-06 from (a) our own week of live evidence and (b) code-level review
of 12 competitor repos (6 hackathon dossiers + 6-repo learning sweep; clones under the
session scratchpad, full mechanism notes in the analyst reports). Rule unchanged: no real
money until the measured system shows live positive expectancy vs its own baselines over
a meaningful sample (≥8–12 weeks paper, attribution-clean).*

## Tier 1 — Learn honestly (build first; makes every later change measurable)

1. **Attribution scoring + gate regret** *(from trdrbot; S–M)* — every selection
   pre-registers a checkable thesis (price band + horizon). At horizon, 2×2 verdict:
   right+profit → strong signal; right-view/wrong-expression → mild credit;
   wrong+loss → penalty; **wrong-but-profited → learn NOTHING** (a lucky win is not
   0.5 signal — it's poison). Declined menu items resolve too → per-gate scorecards
   ("% of your refusals that would have won"). Substrate: our menu/regret book (70% done).
2. **Counterfactual repricing of rejects** *(VegaGuard; M)* — reprice every rejected
   candidate at +15/30/60 min with conservative fills; dedupe repeat scans into one
   opportunity id. Upgrades funnel journaling from "why we said no" to "what no cost".

## Tier 2 — Trade the right regime (fixes our actual week-1 failure mode)

3. **VRP regime router** *(idea from Nexus-Agent; M)* — IV/RV ratio (close-close +
   Parkinson RV) buckets each cycle into sell_premium / buy_vol / stand_aside; 25Δ skew
   z-score vs per-symbol priors picks WHICH wing to sell (rich puts → put credit; rich
   calls → call credit; |z| huge → distrust data). Directly answers the week's core
   flaw: we sold record-cheap premium because nothing measured whether premium was
   worth selling. Also the principled gateway to debit spreads when vol is cheap
   (the mentor question).
4. **Regime-as-control** *(alpaca-gatekeeper; S–M)* — compile the model's own regime
   call into binding deterministic policy: allowed structures, size multiplier,
   direction bans ("no bear calls against bull structure" as code, not vibes).
5. **Blackout-aware expiries + post-print IV check** *(ThetaGuard; S)* — refuse any
   expiry whose life crosses a macro window (we blackout entries yet happily HOLD
   through NFP); after a print, re-verify IV floor before resuming selling.

## Tier 3 — Size and exit like a professional

6. **Calibration-shrunk fractional Kelly** *(trdrbot; M)* — record the selector's
   stated probability on every pick AND decline; measure calibration
   (Ferro-Fricker/Murphy, ~300 LOC pure-Python lift); shrink size toward flat until
   trust is earned (n<8 → half-size regardless). Confidence becomes a measured,
   size-earning input. Gate reads STATED probability (shrinkage sizes, never vetoes).
7. **Exit engine upgrades** *(trdrbot + ThetaGuard + Should-AI-Buy; S–M each)*:
   - corroborated stops: before trusting a wide option print, require the UNDERLYING
     to confirm (session move ≥ 0.25× expected, signed by delta) — credit-spread
     marks are the classic wide-print victim;
   - N-of-M debounce with frozen-when-closed signals (no overnight tick pre-firing);
   - all-legs-or-nothing close with a retried `closing` state (partial spread close
     = naked short);
   - resting GTC take-profit placed at fill + polled stop that cancels it first;
   - force-close at DTE ≤ 2 (pin/assignment risk — we had no such exit).
8. **Agent-authored tripwires** *(alpaca-mind; M–L)* — at selection, the AI arms its
   own invalidation watches ("wake on QQQ > 715"); a zero-LLM-cost sentinel evaluates
   between cycles, protective re-fire-until-answered, fail-open time windows. Closes
   the 30-minute blindness.

## Tier 4 — Evolve safely (the flagship merge)

9. **Shadow paired A/B promotion for the nightly engineer** *(trdrbot; L)* — our gate
   proves changes CORRECT; theirs proves changes BETTER. Add an evidence tier: a
   challenger (start with ONE data lever: candidate-builder config as validated YAML)
   runs against the incumbent on identical live cycles, writes nothing (no-op ledger
   object, never a `shadow=True` branch), promoted at P(better)≥0.90 over ≥8 paired
   runs, futility-refuted at P≤0.05, graveyard prevents re-proposals, sentinels catch
   reward-hacking (entropy floors) and churn. Posterior math is ~80 LOC pure Python.
10. **Structural safety schema** *(trdrbot; S)* — the engineer's hottest editable
    surface becomes validated data (structure/param schema; validator in frozen code
    proving bounded loss on synthetic boards inside the auto-revert gate), not open
    Python.

## Ops hardening (each ≤1 day; each closed a real money-losing incident somewhere)

- Heartbeats distinguishing "ran, nothing to do" / "ran, produced" / "silently dead"
  (our claude-not-found night was exactly this class) — trdrbot `health.py` pattern.
- Content-derived `client_order_id` = hash(batch + sorted legs): crash-retry of a
  nondeterministic LLM can't double-open.
- Reconcile-before-exits ordering as an invariant (exits never act on stale state).
- Matched-spread structural gate: every short leg must have ratio-matched long cover
  (Meridian) — catches malformed multi-leg proposals before limits even apply.
- Rolling 5-day circuit breaker (pause until manually cleared) + post-trade
  buying-power *utilization* cap (Meridian).
- Exact-plan approval hash with 5-min TTL: what was gated is byte-what gets submitted
  (VegaGuard).
- Gate taxonomy: data-quality gates fail OPEN with journaled measurement; money-
  bounding gates fail CLOSED; journal measured values on pass too (gatekeeper).
- Resize-to-budget instead of reject when only size is wrong (gatekeeper).

## Research shelf (interesting, not yet scheduled)

- Typed claim graph with targeted REFUTATION claims (Should-AI-Buy) — a future
  critic design stronger than free-text skepticism.
- QASIX's unit-tested payoff functions — if we ever add the wheel (CSP/covered call).
- Copilot mode (1-click human approval per trade, SentryTheta) — for a real-money
  transition someday.
- Agent-as-MCP-server (VibeHedge) — expose the agent's own tools for inspection.

## Week 1 status (2026-09-06) — SHIPPED
- [x] Protections Gate 0 (cooldown / stop-streak / drawdown fail-closed / low-profit) — journal-computed, funnel-journaled, 7 tests
- [x] Content-derived idempotent order ids for opens (closes stay unique by design)
- [x] Content-hash selector cache (quote-noise-tolerant, book-aware, same-day, env toggle)
- [x] Real-price lab layer `lab_real_prices.py`: Alpaca historical option bars + optopsy-style conservative fills + first-crossing exits.
      VALIDATED against our own live week: QQQ 725/730 replay -> stop on 09-03 (-$112 vs real -$91..-$104); SPY 756/751 -> profit target 09-03 (+$42 vs real +$37). Same days, same reasons.
- [ ] Next: full ladder revalidation on real bars; order FSM; startup event materialization; ClampEvents; abstain-vs-neutral audit

## Round 2 — ecosystem sweep additions (2026-09-06: freqtrade, nautilus_trader,
## optopsy, TradingAgents, ai-hedge-fund, FinMem)

### The headline: the lab graduates to REAL option prices *(M; do first)*
Alpaca's historical options endpoints (`/v1beta1/options/bars`, trades) cover
**since Feb 2024 on the free plan** (200 calls/min, ≤100 contracts/request) — our
entire 16-month window. No historical NBBO quotes, so: real daily bars for marks +
optopsy's slippage models on top. Adopt from optopsy (small, pandas, licence-
compatible): its chain-row schema, `_calculate_fill_price` (mid / half-spread /
liquidity-scaled / per-leg penalty) + commission model, and its vectorized
first-threshold-crossing exits (exactly our 50% PT / 2× stop semantics). Keep
Black-Scholes only as fallback for unquoted strikes. This converts the lab's one
confessed weakness — proxy pricing, relative-only claims — into measured
real-price P&L, and every past and future lab number gets more credible at once.

### Protections: a deterministic "Gate 0" *(freqtrade; S)*
Durable locks in a `protections` Postgres table, checked before both gates:
- **CooldownPeriod** per underlying after any stop-out (would have stopped the
  LLM re-shorting QQQ 30 min after a stop);
- **StoplossGuard**: N stop exits within a window → halt new entries (2 stops in
  a session = the vol regime moved);
- **MaxDrawdown** global lock over a lookback (the account-level breaker we lack);
- **LowProfitPairs**: chronic-loser symbol lock.
Each is <100 LOC of SQL-over-journal; locks survive restarts by construction.

### Order lifecycle + reconciliation as first-class *(nautilus_trader; S–M)*
- ~40-line explicit order FSM (dict of legal (state, event) transitions) that
  RAISES on illegal journal transitions — silent broker-state drift becomes loud.
- Cron-start reconciliation that materializes missing events (fills/assignments
  that happened while we slept) as corrective journal rows BEFORE gates run.
- Expiration as an explicit lifecycle event: expiry-eve flatten rule + settlement
  journal entry, never an implicitly vanishing position.

### Lookahead tripwire *(freqtrade's bias detectors, adapted; M)*
Truncate-and-diff regression test: recompute every gate/selector input with data
cut at decision time and assert identical decisions. Cheap standing guard against
the lab's — and the nightly engineer's — subtlest failure mode.

### LLM-layer upgrades *(TradingAgents / FinMem / ai-hedge-fund)*
- **Content-hash selector cache** *(S)*: hash the fact bundle (excluding as_of);
  unchanged facts since last cycle → skip the paid LLM call. Cost, latency, and
  decision-consistency win on a 30-min cadence.
- **ClampEvents** *(S)*: every gate veto/resize emits {limit, before, after} into
  the journal — "conviction requests, risk disposes", with receipts.
- **Abstain ≠ neutral** *(S)*: audit our ablation books so abstentions are
  excluded from blends/denominators rather than counted as neutral opinions.
- **Lessons memory, done auditable** *(M)*: two-phase pending→resolved lessons
  table (realized P&L + 2–4-sentence reflection), retrieved point-in-time and fed
  to the selector as CITED FACTS; leakage rules pinned as regression tests.
- **Citation credit assignment** *(S, after lessons)*: selector cites lesson-ids;
  resolution adjusts earned_score only on cited lessons — learned relevance
  without FAISS or statefulness (FinMem's one non-theater mechanism).
- **Anti-anchoring prompt devices** *(S)*: "the other side has not spoken — open
  with your own case"; "do not manufacture a direction merely to appear decisive"
  (in schema descriptions, so prompt edits can't lose them).
- **Backtest = live loop** *(M, direction)*: converge the lab toward iterating the
  production cycle function over history with a SimBroker + per-cycle receipts —
  point-in-time correctness by construction (pairs naturally with the optopsy port).

## Suggested sequence (revised after round 2)

**Week 1**: lab-on-real-prices + optopsy machinery; protections Gate 0; order FSM +
startup reconciliation; the cheap S items (selector cache, ClampEvents,
abstain-vs-neutral, heartbeats, content-derived order ids).
**Week 2**: Tier 1 learning instruments — attribution + gate regret, lessons table,
citation credit, counterfactual repricing; calibration recording starts.
**Weeks 3–4**: Tier 2 regime router + regime-as-control; Tier 3 exit upgrades +
calibration-shrunk sizing; lookahead tripwire.
**Then ≥4 weeks untouched paper runway**, measured by the new instruments, while
Tier 4 (shadow paired A/B promotion) is built alongside without touching live
behavior. Real money remains a question we ask the DATA at the end of the runway,
not the calendar.
