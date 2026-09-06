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

## Suggested sequence

Weeks 1–2: Tier 1 + ops hardening (mostly nightly-engineer-implementable under review).
Weeks 3–4: Tier 2 regime layer + Tier 3 exits. Then ≥4 weeks of untouched paper
trading measured by the Tier-1 instruments; only then Tier 4 and the sizing ladder.
Real money is a question we ask the DATA at the end of that runway, not the calendar.
