# Nightly engineer log

One dated entry per evening session — what the evidence showed, what changed, what to watch. Written by the Fable engineer (see prompts/evening_engineer.md); kept only when the verification gate passes.

## 2026-09-04 evening (reviewing trading day 2026-09-04 — day 5, post-deadline)

**The headline is not a selection problem — it's a lifecycle asymmetry.** The
contest deadline (`CONTEST_END_UTC` = 2026-09-04T15:00Z) passed at midday.
From 13:00Z onward, `risk_gate.should_force_close`'s contest trigger fired for
every open spread ("deadline within 2 hours" — a condition that never
un-latches once true), but *nothing blocked new entries*. Result: a churn
loop all afternoon. Every position opened after 13:00Z was force-closed by the
next cron cycle ~30 minutes later, labeled `closed_expiry`, booking roughly
the bid/ask spread as a loss each time: real book ids 13–22, eight completed
round-trips (−$5 to −$35 each, −$134 total ≈ the whole day's real P&L). The
shadow (−$105/16 opens) and random (−$92/10 opens) books ran the identical
treadmill, because all books draw from the same menu. The judge's *decisions*
were fine in isolation — reasoning cited real facts, XLE's ADX-28.97 trending
pick was coherent, and abstentions on the weak SPY/QQQ ranging slate were
correct — but every one of those decisions was moot the moment it was made.

**Evidence (per analyze-regret).** Ablation: all three books negative and
within noise of each other today; the dominant loss driver is the churn
regime, not policy, so no judge-vs-rule conclusion is drawable from today.
Regret: 30 dropped candidates, only 4 marginally positive (+$29.6 total, best
+$15.1) against −$924.9 for the drops in aggregate — the judge's drops were
overwhelmingly right; no class-(b)/(c) pattern, no prompt change warranted.

**Change (one theme: entry/exit symmetry around the force-close window).**
- `risk_gate.py`: new `in_contest_close_window()` — the contest-trigger
  condition factored out of `should_force_close` so entry and exit sides
  share one definition and cannot drift. Exit behavior unchanged.
- `bot.py`: `run_cycle` now skips candidate screening while the window is
  active (same idiom and precedence as the macro-blackout block); exits stay
  fully active. This is a pure tightening: it forbids opening positions the
  exit logic is already committed to flushing at a cost.
- `tests/test_contest_entry_block.py` (5 tests): window boundary at
  deadline−2h, never-unlatches after the deadline (the exact bug state),
  entry-block ⇔ exit-trigger symmetry across sample times, and the DTE≤1
  trigger pinned as independent of the contest window.

**Consequence the operator must know.** With `CONTEST_END_UTC` still at
2026-09-04T15:00Z, the bot is now correctly dormant on the entry side
(exits-only) — before this fix it was dormant *in effect* but paying ~$17/
round-trip for the privilege. To resume paper trading post-hackathon, extend
`CONTEST_END_UTC` in `.env` (which I may not touch); that single change
re-enables entries and pushes the force-close horizon out consistently.

**Proposals (not touched tonight).**
- `bot.py:591` calls `db.record_cycle` once *per opened spread*, so a
  two-open cycle writes two identical cycle rows (today's cycles 100/101,
  4 s apart, same reasoning — confused me for a double cron run until I read
  the code). Fix is small (record once, reuse the id) but it's DB-write
  plumbing next to the order path, out of tonight's theme.
- Status labeling: a contest-window force-close records `closed_expiry` on a
  10-DTE spread. A distinct `closed_force` status would keep expiry
  statistics honest if anyone analyzes exit reasons later.

**Watch tomorrow.** Cycles during market hours should journal
"No new positions: contest deadline …" with zero candidates screened and zero
shadow-book opens; the two spreads that were open at today's close (QQQ
705/700 bull put, XLE 65/70 bear call, both exp 09-14) should be force-closed
at the first RTH cycle — that pair is the last real churn cost. If any *new*
spread appears in the book while the deadline is unchanged, this fix failed.

## 2026-09-03 evening (reviewing trading day 2026-09-03 — day 4)

**Verdict on last night's prediction: CONFIRMED, decisively.** The book-aware
judge did exactly what the fix promised: same-strike duplicate opens went
from 6/day to **0**. All seven abstentions after the cycle-76 open cite
`[QQQ_OPEN_SPREADS]`/`[QQQ_OPEN_MAX_LOSS]` explicitly, and the one spread it
did open (QQQ 705/700 bull put, cycle 76) came the cycle after the morning
stop-outs emptied the book — it cited the zero-exposure fact as part of the
case for acting. No escalation to a pretrade_gate duplicate cap needed; the
informational lever was sufficient. The cost of the old blindness also
realized today: all six stacked QQQ 725/730 bear calls stopped out into
QQQ's +1.18% rally, −$91…−$104 each, ≈ −$587 — that cluster IS the day's
−$474 P&L. The exits themselves behaved as designed (all six consistent,
~2.3x credit cost-to-close).

**Evidence (per analyze-regret).** Ablation: LLM book ≥ rule ≥ random, and
today the gap is causal, not noise — the mechanical shadow rule, which has
no book facts, stacked six clones of the same QQQ 705/700 bull put today
(exactly yesterday's live failure mode) and also took a deep-ITM XLK
artifact now marked −$203. Regret: `dropped_positive_count = 1` (+$15.1,
open mark, cycle 74 — dropped with 6 QQQ spreads open and signal 0.004;
class (a), sound reasoning, noise). The judge is currently the *strongest*
link. The real pattern is class (c), second day running: **spread_builder
again emitted a deep-ITM bear call on stale indicative mids** (cycle 71:
XLK 177.5/182.5, spot ~185.85, credit $358 > max loss $142), the exact
recurrence yesterday's watch item №2 defined as the trigger to fix it.

**Changes (one theme: the builder must only build real OTM credit spreads).**
1. `spread_builder.py`: the short-leg candidate list now requires the strike
   to be OTM relative to spot (`strike < spot` for bull puts, `> spot` for
   bear calls) *before* the delta sort. Mechanism of the bug: the delta
   target (0.13) normally guarantees OTM, but only among liquidity-passing
   strikes — when the indicative feed quotes the whole OTM side too wide,
   only ITM strikes survived and the closest-to-target among them won. Now
   that situation correctly yields "no viable spread plan". This is a
   tightening in candidate construction; live selections today (QQQ 705/700
   short at spot ~717) are unaffected.
2. `bot.py` vol-filter rejection message: `.2f` → `.3f`. Today's journal
   said SPY was rejected because "percentile 0.10 below 0.10" — a strict-`<`
   check plus two-decimal rounding (real value ≈0.095–0.099). Display-only
   fix so the journal stops contradicting itself; threshold untouched.
3. `tests/test_spread_builder_otm.py` (5 tests): ITM-only-liquid chains
   yield None for both directions, OTM shorts still build (and ITM strikes
   are excluded even when liquid), plus a regression pin of the exact
   cycle-71 XLK shape (credit > max loss → None).

**Watch tomorrow.** (1) Menu/shadow books should contain zero rows with
credit > max loss or ITM shorts; XLK may now produce fewer candidates —
that's the correct outcome, not a regression. (2) SPY's real vol percentile
is now visible at three decimals: if it hovers at 0.09x for days while SPY
moves >1%, that's the evidence base for a lab experiment on the 0.10 floor
(`run-lab-experiment`), not a guess — do not just lower it. (3) The one
open QQQ 705/700 bull put (credit $79, marked ≈ −$10). (4) Shadow rule
still stacks clones by design — it's the un-book-aware baseline; leave it
as the control arm, don't "fix" it to match the judge.

**Proposed, not touched.** Nothing outside my lane tonight; the pretrade
duplicate-cap escalation is explicitly cancelled per the confirmed
prediction.

## 2026-09-02 evening (reviewing trading day 2026-09-02 — day 3)

**Evidence.** First day with real AI flow — the ADX-gated trend filter (L3b,
flipped live yesterday) delivered the menu it promised. Per analyze-regret:
ablation is one day of marks and inconclusive (LLM book ≈ −$124, shadow rule
≈ −$180, random ≈ −$96 — noise); regret is actually *good* for the judge
(`dropped_positive_count = 0`: every dropped candidate is negative, XLK
−77.5/−48.5, SPY −30, while its QQQ pick is the best menu row at −15.5, and
it correctly refused the deep-ITM XLK 180/185 whose $286.5 "credit" exceeded
its max loss — a stale-mid artifact, see watch item). The real pattern is
elsewhere: **cycles 53, 54, 62, 63, 65, 66 each opened the identical QQQ
725/730 Sep-14 bear call — six clones, ~$2,510 max loss on one strike** —
and in every one of those cycles the judge's journaled reasoning claims
restraint ("holding back a slot in the concurrent budget", "one clean spread
beats padding the book") while unknowingly padding the book with the same
spread. Six same-day decisions, same missing fact → pattern, class (c):
the packet misrepresents reality by omission. No gate misbehaved: the
per-underlying cap is 20% of equity (~$20k) and the concurrent cap is 8, so
stacking is legal by design (D21 sized these caps for loss-percent, not
duplication) — but the *judge* was structurally unable to weigh it: the fact
packet contains zero book state. The shadow rule stacked identically, which
confirms this is not an LLM quirk but an information gap.

**Changes (one theme: make the judge book-aware).**
1. `bot.py`: new `_book_context_facts()` — every candidate now carries
   `{TKR}_OPEN_SPREADS` (count of open spreads on that underlying) and
   `{TKR}_OPEN_MAX_LOSS` ($ exposure), from the same broker-reconciled DB
   read the risk gate already uses (the loop computing `existing_exposure`
   now also counts per-underlying spreads). Additive facts — journal,
   dashboard audit page, and shadow/menu books all take the list generically.
2. `llm_reasoner.py` SYSTEM_PROMPT (per tune-reasoner-prompt): new bullet
   explaining the two facts, stating that re-selecting a held ticker STACKS
   risk rather than replacing it, and that adding on must be a deliberate,
   cited choice — prefer a different sound candidate or abstention when the
   book already carries that thesis. JSON contract, citation rule, and
   abstain-on-failure untouched.
3. `tests/test_book_context_facts.py` (5 tests): held/unheld values, full
   D10 provenance shape, citation-regex compatibility, and prompt↔fact-name
   coupling (rename the facts and the prompt test fails).

**Falsifiable prediction for tomorrow.** If QQQ (or any name) fires
repeatedly again, same-strike duplicate opens per day drop from 6 to ≤2, and
any add-on decision cites `[..._OPEN_SPREADS]` explicitly. If the journal
shows the judge still stacking without ever citing the book facts, the
prompt lever failed → escalate to a code-level duplicate-exposure cap in
`pretrade_gate.py` (a tightening, D9 already lists "duplicate exposure" as
intended gate content — I deliberately did NOT add it tonight; D21
deliberately raised activity caps and a hard cap on day 1 of real flow would
fight the operator's stated activity goal before the informational fix gets
one day of evidence).

**Watch tomorrow.** (1) The prediction above — verdict it either way.
(2) `spread_builder` offered a deep-ITM XLK 180/185 bear call (spot 183.56)
at cycle 53 with credit ($286.5) > max loss ($213.5) on indicative mids; the
mechanical shadow rule took it and it's the worst shadow row (−$77.5). If it
recurs, a min-OTM / max-credit-sanity check in the builder is a cheap fix.
(3) Morning lost 5 cycles (15:00–17:00Z) to reconcile_block from the manual
dry-fill incident — team fixed it same day (commits f68da27, 794ade9);
nothing for me to do, but tomorrow's cycle count should be full.
(4) XLK still intermittently dies in spread_builder ("no viable spread plan"
in 3 of 5 open-market cycles) — third day; diagnostic theme candidate.

## 2026-09-01 evening (reviewing trading day 2026-09-01 — day 2)

**Evidence.** Second consecutive day with an empty menu: all 12 cycles skipped,
ablation books and menu_regret still empty, judge still unexaminable — per the
analyze-regret procedure the weak link is upstream of the menu, but this time
last night's funnel observability names the stage. In every screening-passing
cycle the **trend filter blocked 100% of surviving tickers**: SPY, QQQ, IWM,
XLF, GLD "Short against bullish trend"; XLE "Long against bearish trend". The
tell is in the filter's own journaled reasoning: it computes ADX, *labels* the
trend weak (SPY 15.0, IWM 16.5, QQQ 11.8, XLF 23.3 — all below the 25
threshold), and blocks anyway — `TrendFilter.check()` never used ADX in the
allow/block decision, only EMA50-vs-EMA200 direction. Structurally this means:
in a long-term EMA-bull regime, any down day generates only bearish intraday
signals, so the entire menu dies on exactly the days credit-spread premium is
richest. 2026-09-01 was such a day — and the blocked bearish signals were
directionally right (QQQ −1.26%, GLD −2.88%, XLK −1.45%; and XLE, blocked
long-against-bearish-EMA, rose +1.33%). One day ≠ proof the gated variant is
profitable, but two days of structural zero-flow + the filter contradicting its
own strength reading = a well-posed lab hypothesis.

**Changes (all dark — live behavior tonight is byte-identical).**
1. `signals/trend_filter.py`: new `TrendFilter(block_only_strong_trend=...)`
   param (default **False** = exact current behavior). When True, the
   counter-trend block only fires when ADX > `adx_threshold` (25); a weak-ADX
   EMA crossover is treated as direction-without-conviction and the candidate
   passes, with an explicit reasoning line. `bot.py` still constructs
   `TrendFilter()` — unchanged.
2. `backtest_lab.py`: ladder gains `L2b ADX-gated trend` and
   `L3b ADX-gated + vol` (same window/seeds; same TrendFilter class live uses,
   so a lab win transfers directly). Also fixed a latent footgun my own edit
   would have triggered: L4's candidate set was captured via
   `name.startswith("L3")`, which "L3b" would have silently hijacked — now an
   exact match on "L3 + vol filter".
3. `tests/test_trend_filter_adx_gate.py` (5 tests): default mode blocks
   counter-trend even at ADX 15 (pins live behavior), gated mode allows at 15
   and blocks at 30, bearish side symmetric, aligned direction always passes.
   ADX is monkeypatched constant — the tests pin the gate logic, not ADX math.

**Not run: the lab itself.** Execution is permission-blocked in this session
(as on 2026-09-01; the external gate is the only runner). **Proposal for the
team:** run `python backtest_lab.py` once — the ladder now prints L2b/L3b next
to L2/L3 on the same window. Read: L3b vs L3 on total P&L *and* max drawdown
(lab caveat: BS/realized-vol proxy, relative comparison only). If L3b ≥ L3
without materially worse drawdown, the live flip is a one-line change in
`bot.py` (`TrendFilter(block_only_strong_trend=True)`); if L3b is worse, the
hypothesis dies cheaply and the variant stays dark.

**Deliberately not changed.** (a) DIA fails the 50k volume floor every cycle
(30–42k on IEX) even after yesterday's 500k→50k recalibration — not chasing
the threshold a second night; either DIA is structurally thin on IEX or it
isn't worth carrying, team call. (b) XLK/TLT die in `spread_builder` ("no
viable spread plan") every cycle — worth one diagnostic look tomorrow if it
persists, separate theme. (c) Vol floor untouched.

**Watch tomorrow.** (1) Whether the team's lab run confirms or kills L3b —
that decides the live flip. (2) QQQ manual bull put stopped out −$70 on the
gap-down open (exit path worked as designed; stop honored at 13:30Z). SPY
756/751 still open, exp 09-10, ~−$85 mark. (3) If trend blocks continue on
green days too, that's a different bug than this hypothesis — check the
journal's per-stage reasons, they now tell you.

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
