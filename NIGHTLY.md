# Nightly engineer log

One dated entry per evening session — what the evidence showed, what changed, what to watch. Written by the Fable engineer (see prompts/evening_engineer.md); kept only when the verification gate passes.

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
