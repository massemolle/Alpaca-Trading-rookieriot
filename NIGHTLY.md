# Nightly engineer log

One dated entry per evening session — what the evidence showed, what changed, what to watch. Written by the Fable engineer (see prompts/evening_engineer.md); kept only when the verification gate passes.

## 2026-09-23 evening (reviewing trading day 2026-09-23 — red tape; a fictional close deadlocked the whole bot from 15:00Z. TEAM ACTION REQUIRED before tomorrow's open — see the SQL below)

**The incident (class (c), order path — it owns the whole afternoon).**
At 14:30:53Z TLT id 35 (81/86 bear call, credit $74) hit its profit
target on TLT's −1.58% day and `manage_open_spreads` submitted the close
(limit debit = 1.1 × the $36 mark). The order rested past the executor's
poll window → `close_spread` correctly returned `status="pending"`,
`fill_credit=None`. Then bot.py's fallback did the damage:
`close_debit = fill_credit if not None else MARK` → realized_pnl became
+$38 (non-None) → the `pending_close` branch, which required
`realized_pnl is None`, was unreachable whenever a mark existed — i.e.
in every non-force-close exit, since `should_close` needs the mark. The
DB recorded `closed_profit +$38` for a fill that never happened. From
15:00Z, every cycle (313–324) reconcile-blocked on the now-"orphan"
broker legs — and `run_cycle` returns BEFORE `manage_open_spreads`, so
the five genuinely open spreads (QQQ 53, XLE 52, SPY 49, XLE 48, XLK 45)
had zero stop/profit-target management for the final six hours of a
−0.71% SPY day, and the shadow/menu books went unmarked too. The close
order (day TIF) expired at the bell: the broker still holds both TLT
legs, the DB still says closed, and reconcile will block again from
tomorrow's FIRST cycle. Compounding discoveries while desk-tracing: (a)
`pending_close` was a dead-end status — set in one place, resolved
nowhere, invisible to the reconciler (had the designed branch ever
fired, the bot would have deadlocked anyway); (b) the reconciler's
qty-consistency check had the same gap for stacked symbols with a
resting entry. The 09-11 session built the pending→rejected path for
ENTRIES; the exit side never got its twin until tonight.

**Team action required BEFORE tomorrow's open (else the bot stays fully
halted — no entries AND, worse, no exits):**
```sql
update <schema>.spreads
set status = 'open', realized_pnl = null, closed_at = null
where id = 35;  -- verify first: status='closed_profit', realized_pnl=38
```
TLT closed 80.465, back below the 81 short strike; on the first clean
cycle the profit target re-fires and the close is re-attempted honestly
under tonight's fix. Strip the fictional +$38 from any P&L reads:
llm_real `recent_7d` is really ≈ −$23 over 17 closes, not +$15 over 18.
Unexplained residue for the team: account cash rose $49.05 between the
16:30Z and 17:00Z snapshots with no DB trade — possibly paper-account
interest; positions were static, but worth an eyeball at the broker.

**Verdicts on 09-22 watch items.** (1) `resolved_dropped_journal`
carried 21 cycles tonight — including ALL FIVE flagged SPY bear-call
drops. Classified below; the oldest open question in this log is closed.
(2) First live `recent_7d`: llm_real {18 closed, +$15, +$0.83/trade}
(fiction-corrected ≈ {17, −$23}), shadow {53, +$478.9, +$9.04}, random
{17, −$579.45, −$34.09}. The rule beats the LLM on the same clock — but
this is not yet the tune-reasoner trigger: the window is one rally week
that paid the rule's QQQ clone-stacking (09-21's same-window read showed
per-trade parity), the virtual arms fill at mid with zero slippage
(09-11 caveat (c)), the FOMC −$346 ages out of the LLM row tomorrow as
predicted, and today's number is corrupted by the fiction anyway.
Re-read on 09-24 with row 35 repaired; two consecutive decisive
same-clock wins for the rule = the trigger stands per 09-22. (3) TLT
id 35 became today's incident instead of resolving quietly. (4) GLD:
two more sub-0.4 drops (0.081 c312, 0.387 c310) — the week tally toward
the screening-bar lab experiment continues, no fills evidence added.

**Evidence (analyze-regret, as charged).** Step 2 from
`ablation_totals`: all-time LLM −$30.82 vs rule −$20.66 vs random
−$41.92 per closed trade (lifetime, era-biased as documented);
`recent_7d` above. Today's judge behavior reads well IN CONTEXT
(market_day: SPY −0.71%, QQQ −0.84%, IWM −1.80%): c311/c312 abstained
on already-stacked long-index names and near-zero fresh signals that
the red tape then vindicated, and c310's one pick (SPY 0.848, a
deliberate stack) was erased by a pretrade-gate CONNECTION error
("Remote end closed connection without response", fail-closed) — lucky
on a red day, and one more exhibit for standing proposal (c)
(single retry on transport errors; get_clock 09-11, pretrade gate
today). Step 3: all-time drops remain net-avoided-losses (77 drops
−$2,345.25 aggregate; the 30 profitable misses +$1,072.5). **The SPY
bear-call drop pattern, classified at last** (c142 +$56, c192 +$57.5,
c193 +$48, c225 +$51, c242 +$30 = +$242.5): read verbatim, every one
of the five cites SPY strength 0.065–0.258 as noise-level, most adding
poorest-R/R-of-slate or already-held — and each strength value WAS
noise-level; no fact was misread, no fact-class recurs as misweighted.
Classification: (a) — individually sound, all five. The residue is a
POLICY hypothesis, not a judge defect: in low-ADX ranging regimes,
far-OTM index credit spreads keep resolving profitable regardless of
directional conviction — directional strength (the axis the judge
correctly applies, and the axis the signals emit) may be the wrong
gating axis for range-regime theta. That is a lab question:
run-lab-experiment on "ADX < 15 slates: take best credit/max_loss ≥ X%
vs abstain", using the menu book as ground truth. Written here for a
quiet evening or a team run — NOT a prompt change; the journals show
the prompt doing its job.

**Changes (one theme: the close path must record only broker truth,
and an in-flight close must be a state every layer understands; no
risk limit, no executor safety path, no DRY_RUN mechanics touched).**
1. `bot.py` close recording: `result.status == "pending"` now ALWAYS
   parks the row as `pending_close` (order ids updated to the close
   order), records NO realized P&L, and notes "order resting, no fill
   yet". The mark fallback survives only for non-pending shapes — the
   DRY_RUN path (`status="dry_run"`) records mark-based closes exactly
   as before, pinned by test.
2. `bot.py` new pending_close resolver (mirrors the 09-11 pending-entry
   resolver, runs before market-hours checks): order filled → book the
   REAL debit via the pinned extractor (both sign conventions tested:
   top-level cost-to-acquire positive, per-leg net); order
   expired/canceled with contracts still alive → row back to `open`,
   falling through so exits re-evaluate THE SAME cycle with a fresh
   mark; contracts expired first → `closed_expiry` with P&L honestly
   unknown; order still working → leave it alone.
3. `reconciler.py`: pending and pending_close legs are now "known
   in-flight" — pending_close legs explain otherwise-orphan broker
   positions, and in-flight symbols skip the qty/side comparison for
   the one cycle the transition lasts. NOT a loosening: any leg not
   explained by a tracked in-flight order still blocks exactly as
   before (pinned by a control test), and without this, change 1 would
   merely convert today's block into a different block — the reconciler
   was only ever "correct" because pending_close never actually
   occurred. Docstring updated to say all this.
4. `tests/test_close_pending_truth.py` (10 tests): today's exact TLT
   shape (pending close books NOTHING, parks pending_close), filled
   close unchanged, DRY_RUN shape unchanged, resolver fill both sign
   paths, dead-order revert-and-resume (the retried close fills in the
   same cycle), expired-contract closure, still-working no-op, and
   three reconciler pins (pending_close legs tolerated / truly orphan
   legs still block / stacked in-flight qty skip).
   `tests/test_entry_fill_economics.py`'s fake DB gained the
   `get_spreads_by_status` method the manage loop now calls.
   VERIFIED IN-SESSION, not just desk-checked: `python -m pytest tests/
   -q` → 174 passed, and `py_compile` clean on every touched module.
   (Session note for the team: the wrapper's exact allowlisted command
   forms DO run — bare `python -m pytest` works; the "execution
   blocked" belief from 09-01/09-21 came from compound/prefixed
   invocations. Recorded in session memory so future nights verify
   instead of desk-checking.) The gate's DRY_RUN cycle will
   reconcile-block tonight against the real broker divergence — that
   is correct behavior and exits 0, so it does not fail the gate.

**Watch tomorrow.** (1) BEFORE anything else: has the row-35 repair
run? If cycles still journal reconcile_block, escalate — every blocked
cycle is an unmanaged book. (2) After repair: TLT close re-fires;
expect a real fill with honest realized P&L, or a "Close submitted TLT
bear_call: … order resting" note followed next cycle by "Pending close
#35 …" — the resolver's first live outing. (3) XLE is the nearest
pressure point while any block lasts: two bear calls (ids 48, 52)
short 63/63.5 vs XLE 62.38 after a +0.99% day. (4) Re-read `recent_7d`
per watch item 2 above. (5) `closed_pending` rows (filled but
price-unreadable) should be rare-to-never; one appearing means the
extractor met an order shape it doesn't know — capture it.

**Proposals (not touched).** NEW (i): on reconcile block, `run_cycle`
returns before ALL exit management — today that cost six unmanaged
hours for five spreads whose own legs verified clean. Managing
broker-verified positions (exits only, no entries) under a block would
preserve the safety guarantee; it changes fail-closed semantics in
run_cycle, so it is the team's call. NEW (j): a resting close keeps
its possibly-junk mark-derived limit until the bell; per-cycle
cancel-and-replace against a fresh mark is order-management machinery
adjacent to proposal (b) (exit mark quality) — team call. Prior
(a)–(h) all still open; (c) gained today's pretrade-gate exhibit.

## 2026-09-22 evening (reviewing trading day 2026-09-22 — flat tape, 3 profit-target closes + 2 opens, disciplined abstentions)

**Verdicts on 09-21 watch items.** (1) `ablation_totals` ran live and
desk-reconciles: `llm_real` {closed_n 42, −$1,429, −$34.02 avg, open_n 7}
— the 22 closes visible in `spreads_all` sum to −$466 (leaving −$963 avg
−$48 over the 20 pre-window closes, consistent with the early-September
era), and open_n 7 matches every account snapshot. First live run clean.
(2) `resolved_dropped_journal` populated (12 cycles) — but NOT with c242;
see below, this is tonight's finding. (3) The correlated long-equity book
did not get its red day: SPY −0.01%, QQQ +0.81%, and three positions hit
their profit targets (QQQ +$40, XLK +$46, SPY +$38 = +$124 realized;
book 8→7). TLT 81/86 (id 35) is still through its short strike, exp
09-28, unresolved. (4) GLD: the judge dropped GLD in all seven slates it
appeared in today (strength 0.24–0.37) — no floor-refused fills tonight
because it never even picked one; the 09-21 screening-bar question stays
open but has no new fills-evidence.

**Evidence (analyze-regret).** Step 2, from `ablation_totals` as charged:
all-time the rule leads per closed trade (−$20.44 vs LLM −$34.02 vs
random −$41.92) — but that lifetime row carries the early-September
stop-outs forever and can never show the judge's current form. Hand-built
same-clock window (closed_at ≥ 09-15, every arm's rows): the real book
closed 16 for −$58 across the FOMC whipsaw, and 11 for +$288 (+$26 avg)
since 09-17 — the "rule > LLM" lifetime read is era-bias, not current
evidence; judge-healthy streak stands at eight sessions and no prompt
change is warranted. Step 3: today's ten drops marked −$12…+$14 — every
citation is stacked-exposure or sub-0.4 strength on the same "index
momentum continues" bet; class (a) across the board, no new pattern. The
12 resolved-drop journals that DID arrive (c245–c282) all read the same
way: correct reserve-slot discipline that a rally happened to pay. **The
finding: the instrument crowd-out.** `resolved_dropped_cycles` is cap=12
newest-first, and the resolved-positive drops newest-first are exactly
c282…c245 — so the flagged 5-for-5 profitable SPY bear-call pattern
(c242/c225/c193/c192/c142, +$242.5) fell at positions 15–23 and was
excluded by the very feature built on 09-21 to classify it. Third
consecutive session c242 ends "unclassifiable", and in a rally the cap
can never drain: fresh class-(a) drops resolve faster than old ones age
out of the 100-row menu window.

**Changes (one theme: finish the window-unbiased evidence instruments;
no trading path touched).**
1. `shadow_book.resolved_dropped_cycles`: cap 12 → 40 with the docstring
   rewritten to say what the cap is (a safety valve) and is not (a
   recency filter). The input is already bounded by the menu query's 100
   rows (~two dozen distinct resolved-drop cycles), so 40 = "all of
   them" in practice; tomorrow's context should carry ~23 journals
   including every flagged SPY bear-call cycle.
2. `shadow_book.ablation_totals` now also emits `recent_7d` per arm
   (closed_n / realized_total / avg over trades with closed_at in the
   last 7 days — ONE cutoff shared by every arm, regime-fair by
   construction; legacy closes without closed_at count all-time only).
   `evening_context.py` feeds `closed_at` through. Step 2 no longer
   needs the hand-computed same-window comparison that both 09-21 and
   tonight required.
3. `tests/test_shadow_book.py`: the two ablation tests updated for the
   new shape (string/datetime/None closed_at coercions, boundary-day
   inclusive, empty-arm), one new same-clock-window test, and the
   resolved-drop test now pins "20 in → 20 out" plus the 40 safety valve.

**Not done, for the team.** The `analyze-regret` SKILL.md rewording
proposed on 09-21 is still unapplied (edits to `.claude/` remain
permission-blocked). Please apply, extended for tonight: step 2 should
read `ablation_totals` — all-time for lifetime, `recent_7d` for current
form — and forbid recomputing arm totals from the windowed row lists;
step 3 should read `menu_regret.resolved_dropped_journal` for resolved
drops' cited reasoning.

**Watch tomorrow.** (1) `resolved_dropped_journal` must now include
c242/c225/c193/c192/c142 — classify the SPY bear-call drop pattern
SAME NIGHT; it is the oldest open question in this log. (2) First live
`recent_7d`: expect llm_real ≈ {16 closes, −$58} shifting positive as
the 09-16 FOMC closes (−$346) age past the cutoff on 09-24 — if rule
`recent_7d` decisively beats LLM on a same-clock read, THAT (not the
lifetime row) is the trigger for tune-reasoner-prompt. (3) TLT id 35
bear call, through its short strike, exp 09-28. (4) GLD screening bar:
seven sub-0.4 drops today; if the week ends with GLD never clearing 0.4,
design the lab experiment from the journaled strengths.

## 2026-09-21 evening (reviewing trading day 2026-09-21 — risk-on Monday, 5 fills + first honest rest→expire, book back at cap)

**Verdicts on 09-18 watch items — both live fixes CONFIRMED.** (1) The
negative-`limit_price` floor now BINDS: all five of today's entry fills
came in at or above their submitted floor (SPY $72 ≥ 68¢, QQQ $79 ≥ 76¢,
XLE $75 ≥ 70¢, SPY $68 ≥ 67¢, QQQ $78 ≥ 76¢ — compare 09-17, when 3 of 5
fills landed BELOW their "limit"), and GLD id 50 delivered the strongest
possible proof: the judge picked it at c281, the order rested at its 50¢
floor on GLD's wide quotes ALL afternoon (`status=pending`, "1 open
orders" in every reconciliation 17:30–20:00Z) and expired unfilled at the
close → row `rejected`, no position. First rest→expire in this bot's
history — 09-17's "expect fewer fills on wide-quoted names, that is the
fix working" happened exactly as written, and it refused a spread that
marks −$15 in the menu tonight. (2) The held-leg guard fired three times
(XLK 10-09 180P and XLK 10-02 180P held-long shorts at 14:00/15:00Z, SPY
10-01 758P held-short long leg at 17:30Z), each falling through to the
next strike with a clean fill after; zero broker 422s today (c266's was
the last). (3) XLK id 43 did not stop — XLK +2.74% carried it to a +$173
mark region; the stale-stop proposal (g) is now low-urgency but still
open. (4) The QQQ stack the judge kept refusing to extend… see below.

**Evidence (analyze-regret first, as charged) — and a near-miss in the
instrument itself.** The naive step-2 read of tonight's context says the
rule book crushed the LLM (+$43 vs −$35 per closed trade). That reading
is FALSE, and the mechanism matters: `shadow_positions` is `order by
opened_at desc limit 60` and the rule book opens ~4× faster than the real
one, so its window reaches back only to 09-16 — the start of a four-day
rally — while `spreads_all`'s 30 rows reach into the 09-09/09-16 selloff
stops. Same-window comparison (opens since 09-16): real book closed 5 for
+$249 (+$49.8 avg, all profit targets), shadow closed 32 for +$1,380
(+$43.1 avg, 31 winners + one −$108 stop). Per trade the arms are at
parity; the total gap is the rule's TEN-deep QQQ clone-stack — marked
−$11…−$21.5 and called out as un-book-aware on 09-17 — getting bailed out
by QQQ +2.78%. One momentum day paying the reckless stacker is variance,
not evidence; judge-healthy streak stands at seven sessions on the
corrected read. Regret: today's dropped-positives (QQQ +26.5/+14/+13.5,
SPY +40/+28/+16.5, XLE +15.5, TLT +10/+6, all marks except SPY c276
+$40 closed) every one cite concentration on an already-stacked name or
strength < 0.3 — and they are all the SAME correlated bet ("index
momentum continues"), not independent decisions. Class (a) across the
board; the judge even took QQQ at c284 when it was the standout despite
RSI 80.9, so it is not rigidly vetoing overbought. All-time menu still
says drops are net-NEGATIVE (−$1,127 across 78; the 36 profitable misses'
+$955 is dwarfed by the −$2,082 of avoided losers). No pattern; the
judge is not the weak link. But c242's SPY 775/780 bear call — the 5th
profitable SPY bear-call drop, flagged on 09-17 with "classify it
same-night from its journal; that row IS within the window" — resolved
today +$30 and was AGAIN unclassifiable: the menu row survived, but the
journal row aged out of `journal_recent`. Twice-costed windowing, tonight
in both instruments.

**Changes (one theme: the evening evidence instruments must be
window-unbiased; no trading path touched).**
1. `shadow_book.ablation_totals()` (pure) + `evening_context.py`: the
   context now carries all-time closed-trade aggregates per arm
   (llm_real / shadow / random: closed_n, realized total, avg per closed,
   open_n) computed from full-table scans of three scalar columns — the
   step-2 comparison no longer depends on regime-mismatched windows. The
   windowed row lists stay, for inspecting individual trades.
2. `shadow_book.resolved_dropped_cycles()` (pure) + `evening_context.py`:
   the cycles behind menu drops that RESOLVED profitable (the exact rows
   step 3 must classify; capped at 12, newest first) get their
   `llm_reasoning` re-fetched into `menu_regret.resolved_dropped_journal`.
   c242-shaped dead ends ("journal outside the window") can no longer
   happen for resolved regret.
3. `tests/test_shadow_book.py`: 3 new tests — per-arm closed-only math
   (incl. numeric-string coercion and `rejected` exclusion), empty-arm
   None-avg, and the resolved-drop filter/dedup/cap.

**Not done, for the team.** (i) I could not update
`.claude/skills/analyze-regret/SKILL.md` — the edit is permission-blocked
in this session. Proposed wording, please apply: step 2 should read the
comparison from `ablation_totals` and explicitly forbid recomputing
totals from the windowed row lists (citing tonight's inversion); step 3
should mention `menu_regret.resolved_dropped_journal` as where resolved
drops' reasoning lives. (ii) c242 itself remains unclassifiable tonight
(its journal is gone from the context; the fix is forward-looking) — the
SPY bear-call drop pattern is now 5-for-5 profitable, +$242.5, and
tomorrow's context should finally let a resolution be read same-night.
(iii) Prior proposals (a)–(h) all still open; (g) re-anchor is
low-urgency after today's rally.

**Watch tomorrow.** (1) `ablation_totals` appears in the context and its
llm_real numbers reconcile with the DB (first live run of the new
section). (2) `resolved_dropped_journal` populates — if any drop resolves
profitable tomorrow, classify it same-night; that has never yet been
possible for an aged cycle. (3) The book is 8/8 with SEVEN long-equity
spreads (SPY×2, QQQ×2, XLK×2, TLT bull-ish) after a +1.6%/+2.8% day —
one red tech day marks the whole book down together; the judge's refusal
to add a 9th is the system working, but exits will be busy. TLT id 35
(81/86 bear call, exp 09-28) is the nearest pressure point with TLT at
81.8, already through the short strike. (4) GLD: if the judge keeps
picking it and the floor keeps refusing the fill, that is the floor
saving us from bad prints — but three refused GLD entries in a row would
argue for dropping GLD's weak signals at the screening bar instead of
burning the judge's slot on unfillable spreads.

## 2026-09-18 evening (reviewing trading day 2026-09-18 — quiet tape, 2 opens + 8 abstentions, first "position intent mismatch" rejection)

**Verdicts on 09-17 watch items.** (1) The negative-`limit_price` entry fix
is CONFIRMED WORKING LIVE: two entries filled today (QQQ 705/700 at c267,
XLK 185/180 10-09 at c270) through the negated-limit path, and both filled
AT or ABOVE their judged credit for the first time on wide-quoted names
(QQQ judged $84 → filled $80 within slippage budget; XLK judged $99 →
filled $92). The alpaca-mcp-server pass-through question (proposal h) is
answered by the fills themselves. (2) XLK id 43 did NOT stop out on quote
width at the open despite sitting $3 from its too-tight stop — XLK rose
+0.84% and the position survived; the stale-stop re-anchor proposal (g)
remains open but less urgent after two green XLK days. (3) GLD id 39
(417/422 bear call) stopped at 13:30Z for −$27 on GLD's +0.63% day —
a normal stop, not a degraded-fill artifact.

**Evidence (analyze-regret first, as charged).** Sixth consecutive
judge-healthy ablation. Per closed trade: real book −$52 avg (22 closed,
−$1,146 all-time), shadow rule −$87 (12 closed), random −$127 (8 closed) —
LLM > rule > random ordering holds. Today the judge abstained 8 of 10
decision slates and opened 2; every one of today's 4 dropped candidates
(XLK c269, GLD c266/268/269, XLE c260) currently marks NEGATIVE (−$7 to
−$26) — zero regret today, and the abstention reasoning (stacked QQQ/XLE
exposure, thin GLD credit, low-ADX regime) reads sound against a market
day where nothing moved more than 0.84%. The shadow rule meanwhile
re-stacked QQQ five more times. No selection pattern; the judge is not
tonight's weak link.

**The finding — class (c), in candidate construction.** Cycle 266 (17:01Z):
the judge selected QQQ, both gates passed, and Alpaca 422-rejected the
order: `position intent mismatch, inferred: sell_to_close, specified:
sell_to_open` (code 42210000). Root cause desk-verified: the book was
already long the QQQ 09-28 700P (hedge leg of spread id 42, 705/700), and
the builder — position-blind — proposed 700/695 on the same expiration.
Its short leg SELLS the very contract we hold long; Alpaca infers a close
per contract and rejects the whole order. Corroboration: menu dedup shows
c266's QQQ candidate collapsed into c243's open 700/695 episode, and
c267's rebuilt 705/700 (short leg = a contract we're already SHORT — same
side, no mismatch) filled cleanly 30 minutes later. Two failure modes hide
here: the loud one (judge's pick erased for a cycle) and a silent nasty
one — had such an order ever filled, it would have stripped the hedge leg
off the existing spread, converting defined risk into a naked short.

**Change (one theme).** `spread_builder` is now held-leg aware: `bot.py`
`find_candidates` collects the option symbols of every open / pending /
pending_close spread into `held_long_symbols` / `held_short_symbols` and
passes them to `build_spread`; the short-candidate walk skips any pair
that would SELL a held-long or BUY a held-short contract, falling through
to the next short in delta order (c266 would have built 705/700 at 17:01
instead of failing). Re-adding on the SAME side — stacking an identical
spread, c267's proven behavior — stays allowed. Executor untouched; no
risk limit moved (the check can only REMOVE order shapes the broker
rejects or that would strip hedges). New `tests/test_spread_builder_leg_collision.py`
(5 tests) pins: default no-op, the c266 short-leg fall-through, the
long-leg mirror, the identical-restack allowance, and exhaustion → no plan.

**Watch tomorrow.** (1) bot.log for "held long leg / held short leg" lines —
each is a c266 prevented; confirm the fallback strikes look sane. (2) XLK
concentration: the book now holds 185/180 on BOTH 10-02 and 10-09 plus
today's +0.84% move — fine while green, but it's the same directional
thesis twice. (3) QQQ triple-stack (2× 705/700 + book exposure $827): a
red QQQ day hits all three at once; the judge already refuses to add a
fourth. (4) Proposal (g) from 09-17 (re-anchor stale stops) still needs a
human call.

## 2026-09-17 evening (reviewing trading day 2026-09-17 — risk-on rally, book refilled 3→8, back at cap by 18:00Z)

**Verdicts on 09-16 watch items.** (1) Menu instrument: healthy — zero
"menu book: cap" lines in bot.log all day (the 20→40 bump holds), and the
sparse-looking regret rows are the by-design dedup on open (short,long)
symbol pairs (e.g. cycles 246–250's QQQ 705/700 candidate was already an
open menu episode from c244), not data loss. (2) SPY bear-call drop
classification: DEAD END by construction — cycles 192/193/225 rolled out
of the DB context permanently before the wider window existed; the pattern
(4 closed profitable drops, +$212.5) stays unclassifiable per procedure.
A 5th instance is now LIVE: c242 dropped a SPY 775/780 bear call (+$3 open
mark); when it resolves, classify it same-night from its journal — that
row IS within the window. (3) XLE: no bounce; id 30 took profit +$58, but
the judge re-added at c244, so the book again carries two XLE 65/70 bear
calls (~$863 combined max loss). Watch item stands.

**Evidence (analyze-regret first, as charged).** Ablation, 5th consecutive
judge-healthy reading: the judge opened 5 of 10 decision slates (GLD c242,
SPY c243, XLE c244, QQQ c246, XLK c251) and abstained 5 — every abstention
citing stacked exposure or thin credit, exactly the 09-14 prompt change's
intent (slot-as-bar-raising language throughout, e.g. c250 "the raised bar
for the single remaining reserve slot"). The shadow rule opened ELEVEN,
including the SAME QQQ 705/700 09-28 bull put six times (c244–c250) — the
un-book-aware control stacking again; its clone-stack marks −$11…−$21.5
each. Realized today: real book +$58 (XLE id 30 profit target), shadow
+$28 (+61, +53 XLE profit-targets minus −86 TLT c193 stop), random +$53.
On marks the arms are within noise; on structure the judge holds 5
diversified names vs the rule's 6-deep single-strike stack. Regret: c243's
dropped QQQ (+$16.5 mark) and TLT (+$17.5 mark) both class (a) — cited
reasoning (QQQ already held, TLT strength 0.112 "essentially noise") reads
sound. No selection pattern. The day's real finding is class (c), and it
is not in the menu — it is in the ORDER PATH:

**Every credit open this bot has ever placed was an unbounded marketable
order: the "limit" never bound, because the sign was wrong.** Mechanism,
verified three independent ways tonight. (a) Broker behavior: 3 of
today's 5 fills landed BELOW their own submitted limit — bot.log shows GLD
submitted `limit_price '0.48'`, filled 0.31/share; XLK '1.0' → 0.88; QQQ
'0.96' → 0.93 — impossible for a binding credit floor. (b) SDK ground
truth: alpaca-py 0.44.0's own LimitOrderRequest docstring — "For the mleg
order class ... a positive value indicates a debit (representing a cost or
payment to be made) while a negative value signifies a credit" — and no
sign validation anywhere in the SDK. A positive limit on a credit spread
means "willing to PAY up to that much", which any credit fill satisfies at
any price: the order just crosses at the market's net. (c) History: zero
entry orders have ever rested or expired (grep: no "Pending #N rejected"
ever), even on 6%-wide GLD quotes — a real floor would have refused those.
This is the same signed-cost-basis convention the 08-30 fix pinned for
`filled_avg_price` (top-level −0.54 for a real $0.54 credit); the price
axis of the ORDER was never re-checked against it. Consequence chain: the
09-11 anchored-floor fix computed the right number (today's five anchors
all verify: max(judged, fresh)×0.9 matches every logged limit) but the
number never reached the broker as a floor; fills are the quote-crossing
net; and stop (2× fill) / profit target (0.5× fill) then anchor to the
DEGRADED fill. Tonight's live exhibits: GLD id 39 filled $31 vs $45.5
fresh mid — its stop is $62, and it marks $43 (69% of stop) while actually
PROFITABLE vs its intended economics; XLK id 43 filled $88 (judged 107.5),
stop $176, 20:30Z crossing mark $173 — born three dollars from its stop on
a day XLK rallied +2.18%. That is the 09-11 XLK death-spiral shape, again,
with the fix "verified" but inert.

**Change (one theme: the floor must reach the broker as a floor).**
`executor_mcp.open_spread` now submits `limit_price = str(-limit_credit)`
— negative = net credit under Alpaca's signed mleg convention. The
negation lives at the API boundary ONLY: `limit_credit_price` and every
internal credit stay positive; `close_spread`'s debit limit is already a
positive cost and is pinned as deliberately asymmetric. This touches the
order-pricing line, not the idempotency or fill-confirmation paths. New
`tests/test_entry_limit_sign.py` (5 tests): open payload negative
(explicit and default-computed), close payload positive, regression pin of
today's GLD shape (the 0.31 fill must violate the submitted limit), and
fill-extraction sign unaffected. No existing test asserted on limit_price
at all (checked — that absence is how this survived three weeks).

**Failure mode if I'm wrong, stated honestly:** the one thing not
verifiable offline is whether alpaca-mcp-server 2.3.0 re-signs or rejects
a negative limit_price string before it reaches alpaca-py (its source
lives in the uv cache, unreadable from this session; the SDK itself
accepts negatives). If it rejects, tomorrow's first entry errors loudly
("ERROR opening ..." in the journal, order fail-closed, nothing placed) —
exits unaffected. Empirics argue it passes through: today's positive
values reached the broker verbatim (fills below the "floor" prove the
broker saw them as debit bounds, untransformed).

**Watch tomorrow.** (1) First open of the day: bot.log "Opening ...
limit_credit=0.XX" must be followed by either a fill with
fill_credit ≥ 100×that floor, or an honest rest→expire through the pending
path. A fill below floor = the fix failed; an immediate error = the MCP
server rejects negative limits (team: verify/bump alpaca-mcp-server).
Expect FEWER fills on wide-quoted names (GLD/XLK) — that is the fix
working, not a regression. (2) XLK id 43: stop $176 vs crossing mark $173
— likely stops at 13:30Z on quote width unless XLK opens strong; if it
stops on a flat/green XLK, that is the exit-side mark-quality defect
(proposal (b), 09-11) firing on a degraded-fill position — evidence for
the team, not something I may loosen. (3) QQQ id 34 (721/726 bear call,
mark ~192 vs stop 200): one more QQQ up-tick stops it; that is the stop
working as designed. (4) GLD id 39's $62 stop is an artifact of the
now-fixed defect; if it stops with a mark far below the ~$96 its judged
economics imply, book it as the bug's trailing cost.

**Proposals (not touched).** New: (g) three open positions born from
degraded fills (GLD id 39, QQQ id 42, XLK id 43) carry stops/targets
anchored ~10–35% too low; re-anchoring them to judged economics is a stop
LOOSENING — team call, and time-sensitive for XLK id 43. (h) verify
alpaca-mcp-server 2.3.0 passes negative mleg limit_price through
(one-line read of its place_option_order in the uv cache). Prior
proposals all still open: (a) SYSTEM_PROMPT hash in reasoner cache; (b)
exit-side mark quality bound (tonight adds two exhibits); (c) get_clock
retry; (d) TLT width lab; (e) L3b adjudication; (f) per-spread
record_cycle duplication.

## 2026-09-16 evening (reviewing trading day 2026-09-16 — FOMC day: five closes, one open, blackout afternoon)

**Verdict on the 09-14 prediction: CONFIRMED, within the readable evidence.**
Entries resumed this morning (the 13:30Z GLD stop freed the first slot) and
the prompt change did what it promised. Cycles 225–227 had candidates and
the judge abstained on all three (shadow opened four positions in that span
— agreement broke from Monday's 6/6); at cycle 228 it opened exactly one,
and the journaled reasoning cites the last slot in the bar-RAISING
direction: "With only 1 slot left the bar is high, and XLE clears it on
conviction" — strength 0.475, trending ADX 27.9, against a QQQ/SPY/GLD
slate of 0.06–0.15 ranging noise it refused despite QQQ's better raw R/R.
No slot/room-as-pro-open citation anywhere readable. Caveat that motivates
tonight's theme: the 225–227 journals themselves fell outside the context
window, so the verdict rests on cycle 228 verbatim plus observed behavior.

**Evidence (analyze-regret first, as charged).** Ablation, 4th consecutive
judge win: the real book realized −$346 today (stale 09-11/09-14 cohort:
GLD −116, GLD −118, TLT −32, SPY −130, plus QQQ 725/730 +50 profit) with
account daily P&L only −$117 as open marks improved; the shadow rule
realized ≈ −$770 (its GLD clone-stack alone −$503) and random ≈ −$739
(its cycle-228 GLD bull-put pick stopped −$227.5 the same afternoon —
the exact candidate the judge refused at strength 0.062). LLM ≥ random ≥
rule. The XLE open marks −$6 on day one; XLE −2.87% today also rescued the
09-11 XLE 65/70 (id 30) that 09-15 flagged as the top pressure point.
Regret classification: cycle-228 drops are class (a) — sound, and the GLD
counterfactual promptly lost. Cycle-225's dropped SPY 772/777 bear call
closed +$51 — the **4th profitable SPY bear-call drop** (c142 +56 = classed
(a) on 09-10, c192 +57.5, c193 +48, c225 +51, +$212.5 total) — but c192/
193/225 are all UNCLASSIFIABLE tonight because their journal rows are
outside the context window. Not actionable per the procedure; unblocking it
is the theme.

**The real defect: both evening evidence instruments silently dropped
today's decisions.** (1) `MENU_BOOK_MAX_OPEN=20` (env unset; code default)
was reached at cycle 225 — bot.log shows "cap 20 reached" skips for ALL
decision-cycle candidates of 226/227/228 today and for cycle 196/197
slates on 09-14: the regret ledger has no row for today's taken XLE, none
for the refused QQQ/SPY/GLD, and none for Monday's cycle-197 SPY bull put
(the judge's one bad open that day). Episodes live up to 14 DTE, so a
20-row cap is below the steady-state backlog and the skip loses exactly
the newest — the rows regret exists to measure. (2) `evening_context.py`
truncated cycles/journal at 12 rows, which for the second night running
cut the morning (225–227) out of the evidence file — the 09-15 proposal,
now twice-costed.

**Changes (one theme: the evidence instruments must carry a full session;
no trading path touched).** `shadow_book.py` menu cap default 20 → 40
(marking load bounded at 40 snapshot calls/cycle worst case; env override
unchanged), pinned by new `test_menu_cap_default_is_40`. `evening_context.py`
`cycles_recent` 12 → 20 (cycles gain a row per opened spread on multi-open
cycles — the 09-04 quirk), `journal_recent` 12 → 16 (a session is 15
half-hour cycles). Both files are read-only analysis infrastructure; risk
limits, gates, and bot.py byte-identical.

**Watch tomorrow.** (1) bot.log should show zero "menu book: cap" lines;
if 40 also binds, the next step is menu-episode hygiene (censor-close stale
rows), not another bump. (2) Tomorrow's context carries 16 journal rows —
FIRST TASK: pull cycles 192/193/225 reasoning if still within window (else
the next SPY bear-call drop) and classify the 4-drop pattern properly;
if it's class (b), the likely misweight is ranging-regime strength on SPY
bear calls. (3) XLE concentration: two live 65/70 bear calls (09-25,
09-30) — today's −2.87% made both comfortable; an energy bounce re-tests
~$818 combined max loss on one name.

**Proposals (not touched).** All prior still open: (a) SYSTEM_PROMPT hash
in `reasoner_cache.menu_hash`; (b) exit-side mark quality bound (loosening
— team call); (c) get_clock retry; (d) TLT per-underlying width lab; (e)
L3b ADX-gate adjudication via team-run `python backtest_lab.py`; (f)
per-spread `record_cycle` duplication (09-04) — tonight's cycles_recent
sizing had to work around it, which is one more reason to fix it.

## 2026-09-15 evening (reviewing trading day 2026-09-15 — full day at the 8-cap, zero decisions)

**Evidence (analyze-regret first, as charged).** Thin by construction: the
book sat at the operator's 8-position cap from open to close, so all 12
market-hours cycles screened nothing — zero candidates, zero menu rows, zero
selections in any book. No new regret classifications are possible and last
night's falsifiable prediction (budget bullet ends slot-citing) got **no
test** — exactly the caveat written 09-14; it stays open, verdict in 1–2
days as positions close. Ablation on standing books still says judge
healthy: the shadow rule realized ≈ **−$588** today (its six stale SPY
~756-strike bull-put clones from 09-11 all stopped 14:30–15:30Z on a quiet
−0.44% SPY day), random realized −$207.5 (two SPY stops), the real book
realized $0 with ≈ −$98 open-mark drift. LLM ≥ random ≥ rule — third
consecutive reading, and the control arm keeps paying for the stacking the
judge refused.

**The one defect today's data does establish: at-cap cycles journal a
falsehood.** Watch item (1) from 09-14 asked whether zero-budget cycles
journal that state honestly. They don't: every cycle today said "No
eligible candidates this cycle" with empty gate_rejections — implying an
empty funnel, when in truth `run_cycle`'s gating `if` short-circuits on
`remaining_budget > 0` and screening never ran. `_skip_reasoning` had
branches for options level, closed market, blackout, protections, and the
contest window, but none for the very first condition in the gate. Same
misattribution class as the 09-07 holiday fix, and it cost analysis effort
tonight for the second time.

**Change (one small theme: the journal must name the operative reason;
display only).** `bot.py::_skip_reasoning` takes `remaining_budget` /
`open_spread_count` and journals "No new positions — book at the
concurrent-spread cap (8 open, 0 remaining budget); not screening. Exits
stay active." The branch sits LAST among the suppressions: blackout,
protections, and close-window are time-bounded external events worth
surfacing even on a full book; at-cap is the book's normal state. The
trade-gating `if` is byte-identical; no risk limit touched. Four new tests
in `tests/test_skip_reasoning.py` pin today's exact case, closed-market and
suppression precedence over the cap, and the cap-lowered-mid-flight shape
(9 open under an 8-cap).

**Watch tomorrow.** (1) First cycle at cap should journal the new cap
message; the first cycle after any close should screen again — if entries
resume, the 09-14 prediction finally gets its test (grep for slot/room
citations). (2) Pressure points on the full book, in order: XLE 65/70 bear
call (id 30) — XLE closed 65.94, the short is ITM after today's +2.17%
move, mark ≈ 151 vs 204 stop; SPY 753/748 bull put (id 37) — short only
0.58% OTM, mark 168 vs 200 stop, one −0.6% SPY morning stops it; GLD
399/404 (id 32) — 1.25% OTM with GLD RV 28%. Expect the cap to free up by
stop or profit-target, not by choice. (3) If a stop cluster fires
(stop_streak max 4 in 24h), entries halt and the prediction wait extends —
read protections before blaming the prompt change.

**Proposals (not touched).** Unchanged from prior nights, all still open:
(a) fold a SYSTEM_PROMPT hash into `reasoner_cache.menu_hash` (intraday
prompt hotfix safety); (b) exit-side mark quality bound / two-cycle stop
confirmation (stop loosening — team call); (c) get_clock single retry
before fail-safe-closed; (d) TLT per-underlying width lab; (e) L3b
ADX-gate adjudication via team-run `python backtest_lab.py`. New, small:
the cycles list in `evening_context.json` truncates at 12 rows, which today
exactly covered 15:00Z→20:30Z and dropped the 13:30/14:00/14:30Z cycles —
on busier days the evening engineer loses the morning; consider bumping to
a full session's worth (~14–16).

## 2026-09-14 evening (reviewing trading day 2026-09-14 — six-open Monday, book at cap)

**Evidence (analyze-regret first, as charged).** Both 09-11 watch items came
back clean: the anchored entry limit is confirmed live — all six of today's
fills landed within the 10% budget of the judged credit (GLD $124 vs $134
mid, QQQ $100 vs $110 — exactly the 90% floor — and $91 vs $96.5, SPY $100
vs $103.95; both TLT fills came in *better* than the judged mid), zero
floor-of-floors donations, and GLD id 31 held all day without a noise stop.
Ablation: LLM ≥ rule, decisively and causally — the shadow rule's six
stacked QQQ 70x bull-put clones from 09-11 all stopped on this morning's
−1.61% QQQ gap (≈ −$761 realized) while the judge's single QQQ position took
−$130 and its SPY bear call banked +$49; shadow's day netted ≈ −$320 vs the
real book's −$81 realized / +$13.6 account P&L. Regret: one dropped winner
(SPY 749/744, +$13 open mark) — noise, class (a). The judge's drops stay
sound. The pattern is on the *taken* side:

**Budget slots are being spent as if unused capacity were a cost.** The
judge opened in 6 of 7 candidate cycles (book 2 → 8, the operator's cap, in
one session) and never abstained; shadow agreement was 6/6. The tell is
cycle 197: SPY refused at strength 0.165 ("simply too weak to open on
conviction", c195) and 0.034 ("essentially noise", c196) was then OPENED at
0.052 — justified as "with the last budget slot the clean-book, best-payout
candidate is the disciplined pick." Same class as 09-08 cycle 135 (third
XLK add filling budget) and the 09-02 stack ("holding back a slot" while
padding): `remaining_budget` cited as a reason FOR the marginal trade.
Class (b) across ≥3 decisions and ≥2 days — the prompt teaches nothing
about how budget should bear on selectivity, so slot pressure LOWERS the
bar exactly when it should raise it. (D21 wants activity, but it raised the
cap so signals could flow, not to make 8 a target.)

**Change (one theme: the last slot is reserve, not space to fill; via
tune-reasoner-prompt).** One new SYSTEM_PROMPT bullet in `llm_reasoner.py`:
`remaining_budget` is a ceiling, never a reason — as it shrinks the bar for
the marginal spread rises; "the book has room" / "last slot" / best-of-a-
weak-slate never justify opening. JSON contract, citation rule, book-facts
bullet, and abstain-on-failure all verbatim-untouched (pinned by new
`tests/test_reasoner_budget_guidance.py`, 5 tests). Cache safety
desk-checked: `reasoner_cache.menu_hash` is same-UTC-day scoped, so no
pre-change decision can be reused tomorrow.

**Falsifiable prediction.** Journaled reasoning stops citing slot
availability/room as a pro-open argument (grep the journal), and abstention
returns on weak slates — LLM/shadow agreement drops below today's 6/6.
Caveat: the book sits at the 8-cap, so entries only resume as positions
close; give this 1–2 trading days of data before verdicting. If the judge
again opens a sub-0.1-strength candidate citing the budget, the prompt
lever failed → next escalation is a menu-level change (e.g. a minimum
mechanical-score floor), lab-tested first.

**Watch tomorrow.** (1) At-cap behavior: cycles with zero remaining budget
should journal that state honestly, exits fully active — eight positions
(2 QQQ bear calls, 2 TLT bear calls, 2 GLD bear calls, XLE, SPY) all get
managed. (2) QQQ ids 34/36 are the exposed pair if tech bounces: ~$802
combined max loss, both born on a down day. (3) Fill-vs-judged spot check
once more — today QQQ filled exactly at the 90% floor once; frequent
exact-floor fills on tight books would mean the anchor is the binding price,
not the market.

**Proposals (not touched).** (a) `reasoner_cache.menu_hash` should fold in
a hash of SYSTEM_PROMPT: today the same-day scope hides it, but any future
*intraday* prompt hotfix would silently reuse pre-fix decisions until
midnight UTC. One line, but it's cache plumbing shared with the team's v2
machinery — their call. (b) Still open from prior nights: exit-side mark
quality (09-11a), get_clock retry (09-11b), TLT per-underlying width lab,
L3b ADX-gate adjudication via team-run `python backtest_lab.py`.

## 2026-09-11 evening (reviewing trading day 2026-09-11 — first full post-breaker day)

**Evidence (analyze-regret first, as charged).** Entries unlocked on schedule
(stop_streak aged out; first open cycle 175 at 14:00Z — 09-10 watch item 1
confirmed) and the 09-10 expiration-fallback fix is confirmed live: GLD built
on-width $5 spreads all day and reached the menu every cycle (watch item 2).
Ablation, today's opens at marks: LLM book 4 opens ≈ −$97 (QQQ −17, XLK −63
realized, XLE −14, GLD −3) > random ≈ −$128 (4 opens) > shadow rule ≈ −$300
(~23 stacked opens) — LLM ≥ random ≥ rule, judge healthy. Regret: 2 dropped
winners (+$2 QQQ c177, +$13 GLD c176, both class (a): weak-signal +
already-held reasoning reads sound) vs 6 dropped losers −$99.5 avoided. No
selection pattern. The day's real loss driver is class (c), but *downstream*
of the menu — entry execution:

**The tolerance stack re-anchors fills 28% below the judged economics, and
the stop then guarantees the loss.** Mechanism, verified against today's
fills: (1) the menu credit is the builder's net MID (judge reasoned on GLD
$68, XLK $53); (2) `pretrade_gate` re-quotes and REPLACES
`plan.credit_estimate` with the fresh mid, tolerating 20% shrink; (3) the
marketable limit floored at `fresh × (1 − 10%)` — floor-of-floors = 0.72 ×
judged. Both wide-quoted names filled EXACTLY there (GLD $51 = 68×.75, XLK
$39 ≈ 53×.74 — a limit can't fill below its floor, so these were floor
fills). (4) The stop is `2 × fill` while the mark is the crossing
(short_ask − long_bid): XLK was born with its crossing cost ≈ 82% of its own
stop and stopped 90 min later at exactly 2.0× (−$39, cost 78 ≈ BS-fair for
the spread) **on a day XLK rose +1.31%** — the loss was the quote width,
realized deterministically, and it then fed the low_profit lock (XLK −$327/7d
→ symbol locked cycles 185+, compounding the damage into tomorrow.)

**Changes (one theme: the executed trade must be the judged trade).**
1. `bot.py`: new `_entry_limit_credit(judged, fresh)` — the limit floor now
   anchors to `max(judged, fresh)` credit, so the entry fills within the
   single documented `max_entry_slippage_pct` (10%) of what the LLM approved,
   or rests unfilled and dies through the existing pending→rejected path
   (reconciler tolerates pending rows; unfilled day orders expire → marked
   rejected next cycle — no new machinery). The gate's 20% shrink check still
   rejects moved markets; it just no longer drags the executable floor down.
   Pure tightening: today GLD would have floored at $61 (not $51) and XLK at
   $48 (not $39) — both likely honest no-fills instead of donations.
2. `bot.py` pending-resolution path: it read the REST order's top-level
   `filled_avg_price` naively — the field CLAUDE.md pins as NEGATIVE for
   credit opens. A pending-resolved fill would have recorded a negative
   credit_received, flipping should_close into an instant bogus
   "profit target" close. Now reuses `executor_mcp._extract_filled_avg_price`
   (per-leg preferred, top-level negated — the 08-30-pinned extractor). This
   path becomes load-bearing under (1), so it's the same theme, not scope
   creep.
3. `tests/test_entry_fill_economics.py` (5 tests): anchor identity when
   fresh is lower, regression pin that today's two floor-fills are refused,
   fresh-improves-takes-higher, and both REST fill shapes (top-level
   negation, per-leg net) through the real manage_open_spreads pending
   branch.

**Watch tomorrow.** (1) GLD spread id 31 is the fix's motivating live case
still on the books: fill $51, stop at $102, crossing mark ≈ $71 at entry —
if it stops on quote noise rather than a real GLD move, that's the exit-side
half of this defect firing (see proposal below). (2) Look for "Pending #N
rejected (expired)" notes / pending rows in the journal — that's the
anchored limit correctly refusing degraded fills; frequent pendings on
SPY/QQQ (tight books) would instead mean the anchor is too aggressive
somewhere I didn't foresee. (3) Cycles 180–181 journaled "Market is closed"
at 16:31Z/17:01Z on a Thursday — get_clock failed twice and fail-safed to
closed (by design), but exits also skipped for that hour; if it recurs,
it's an availability pattern, not a one-off.

**Proposals (not touched).** (a) Exit-side twin of tonight's fix: the stop
mark is the indicative-feed crossing (short_ask − long_bid) with no quality
check — the menu-book XLK stopped at mark 116 vs ≈70 BS-fair on a green day,
so one wide/junk quote cycle can book a permanent realized loss. A mark
sanity bound or two-cycle stop confirmation would fix it but is a stop
LOOSENING — team call, written here for review. (b) get_clock: one retry
before fail-safing to closed would have saved an hour of exit management
today (bot.py:520). (c) Ablation bias now visible: shadow/random books
"fill" at the mid estimate with zero slippage while the real book pays real
fills — after tonight's change the real book's fills are within 10% of mid,
but book-vs-book P&L comparisons still flatter the virtual books by the
slippage the shadow never pays. Still open: TLT per-underlying width lab,
L3b ADX-gate adjudication via team-run `python backtest_lab.py`.

## 2026-09-10 evening (reviewing trading day 2026-09-10 — breaker day)

**Evidence (analyze-regret first, as charged).** Zero fresh decisions to
classify: the 13:30Z open stopped out all four stale spreads at once (QQQ
705/700 −$99, XLK 185/180 −$129, XLK 182.5/177.5 −$99, XLE 67/70 −$47 — all
opened 09-04/09-08 under pre-fix selection), `stop_streak` hit its max-4
count on that single exit cycle, and every cycle until the close skipped
entries. Ablation on the standing books instead: the judge's one live
position (SPY 775/780 bear call from 09-09) marks ≈ +$24; the shadow rule's
09-09 cohort netted ≈ −$230 (its stacked XLK bull puts all stopped, its SPY
bear-call clones took profit +$50–56 — the same trade the judge holds);
random ≤ rule. LLM ≥ rule ≥ random → per the procedure, the judge is
healthy. Cumulative regret agrees: 44 dropped candidates would have lost
−$1,346 total; the 7 dropped winners sum to +$94, and the best single miss
(+$56, SPY bear call, cycle 142) was refused on book-exposure reasoning
that reads sound — class (a), not evidence. No pattern; nothing to tune in
the reasoner tonight.

**Change (theme: nearest expiration THAT BUILDS — executing my own 09-09
proposal; `spread_builder.py` + tests).** The builder committed to the
single nearest expiration in the DTE window; if that chain couldn't build,
the ticker died for the cycle (GLD post-long-leg-fix: only width-1 409/410-
style geometry, ~$10–20 credit vs ~$85 max loss, because the 09-21 chain
tops out at 420 — the proper spread lives one expiration up). Now
`build_spread` walks expirations nearest-first (cap 3 attempts, one
snapshot batch each — extra calls happen only where the ticker previously
died): the first plan whose width is within ±50% of `spread_width_dollars`
wins, so healthy SPY/QQQ/XLK behavior is byte-identical (nearest expiration
still preferred for theta); an off-width plan is kept only as a last resort
when nothing in the window builds on-width — a strict superset of current
capability, no ticker that builds today is lost. Per-expiration logic is
factored into `_build_for_expiration` unchanged. New
`tests/test_spread_builder_expiration_fallback.py` (5 tests): chain-top
width-1 defers to the next expiration, unbuildable-nearest falls through,
on-width nearest wins immediately, all-off-width returns the nearest as
last resort, attempts capped at 3. Existing OTM/pagination/long-leg tests
desk-checked — all single-expiration, chosen strikes unchanged.

**Watch tomorrow.** (1) `stop_streak` ages out ~13:30Z (the four stops
leave the 24h window right at the 09-11 open) — entries should unlock in
the first or second cycle; if still halted mid-morning, read the
protections window bounds before assuming new stops. (2) GLD should now
reach the menu with on-width geometry from the further expiration, or die
honestly at liquidity — the funnel journal names the stage, and the new
"builds only at N% of target width" log lines say when fallback fired.
(3) If bot.log shows a ticker burning all 3 expiration attempts every
cycle, that's a universe-review candidate, not a retry problem.

**Proposals (not touched — protections may not be loosened by me).**
`stop_streak` counted four stops from ONE 13:30Z exit cycle as four
independent events and halted a quiet, premium-rich day (the shadow book's
SPY bear calls printed +$50–56 while we sat out) over positions the current
judge provably wouldn't re-open (its eight 09-09 abstentions refused
exactly these re-adds). If the breaker is meant to stop *decision streaks*,
counting distinct exit cycles instead of positions would preserve that
guarantee without double-charging one gap open — that is a loosening, so
it's the team's call, written here for review. Still open from prior
nights: TLT per-underlying width (lab experiment), L3b ADX-gate
adjudication via a team-run `python backtest_lab.py` on real bars.

## 2026-09-09 evening (reviewing trading day 2026-09-09 — restored 2026-09-10)

*This entry was lost with the gate's false-positive revert (128/129 passed;
the one failure was the env-coupled blackout-date test, since fixed). The
team re-landed the code and tests on 09-10 (commits 18c9270, 5322cd1) but
the diary entry went missing — restored here from the saved session review.*

**The day in three sentences.** The 09-08 pagination fix is confirmed
working (SPY candidates normalized to real 755/775 strikes with $78–96
credits, `page_token` followed cleanly, no fallback warnings), and the
judge had its best day yet: eight consistent abstentions citing book
exposure, one clean fresh open (SPY 775/780 bear call), ≈ −$67 attributable
on the day versus the shadow rule's ~20 stacked clones at ≈ −$408 — and the
XLK re-adds it refused finished −$26.5 and −$100.5, so the stacking
flip-flop pattern is dead by the 2-day evidence bar. But the un-truncated
chains exposed a second pipeline layer: GLD died every cycle with
"non-positive credit (0.00)" because its 09-21 chain tops out at 420 while
the delta target sits near 431, so the long-leg snap landed on the short
strike itself — a same-strike non-spread — while TLT/XLF died because only
the single delta-best short was ever tried and one junk long-leg quote lost
the whole ticker.

**Changes made.** `spread_builder.py`: the long-leg snap now only considers
strikes strictly further OTM than the short (same-strike and
structure-inverting snaps impossible by construction; chain-edge shorts are
excluded from the shortlist before quoting), and selection walks the liquid
shorts in delta order taking the first with a tradeable long leg — zero
extra API calls. All data-quality guards and liquidity thresholds
unchanged. `tests/test_spread_builder_long_leg.py` (5 tests) pins the GLD
chain-top shape, its bull-put mirror, the TLT/XLF fall-through, and both
no-plan exhaustion paths.

**Open risks.** (1) GLD's rescued candidates will be narrow (~419/420,
~$10–20 credit vs ~$85 max loss) because the nearest expiration forces
width-1 — the real fix is expiration fallback ("nearest expiration *that
builds*"), proposed for the next session. (2) TLT is likely structurally
untradeable at $5 width on an $82/10%-vol underlying — proposed as a lab
experiment on per-underlying width, not patched. (3) QQQ's low_profit lock
ages out ~15:30Z on 09-10; the 5-position live book (2 XLK at $837.5
combined max loss, SPY, XLE, QQQ exp 09-14) stays under normal management.

## 2026-09-08 evening (reviewing trading day 2026-09-08 — first live day on Roadmap v2 W1 code)

**Evidence (analyze-regret first, as charged).** Ablation, today only: LLM
book 4 opens (mark ≈ −$128), shadow rule 15 opens (−$309.5 — it stacked
XLK@182.5 five times), random 4 opens (−$86). Regret: dropped-positive is
trivial (6 rows all-time, +$37.6 total, best +$15.1) and every one of
today's drops reads sound against the cited facts — the judge's *rejections*
are not the weak link. Two real patterns instead:

1. **Pipeline (class c) — the chain fetch truncates dense chains.**
   `spread_builder._fetch_contracts` called `get_option_contracts` with
   `limit: 100` and never followed `next_page_token` (documented in the
   module's own docstring since 08-26). SPY's dense Friday 09-18 expiration
   exhausts 100 puts ~150 points below spot, so delta targeting only ever
   saw deep-OTM strikes: every SPY candidate today (cycles 126–135) was the
   same degenerate $1-credit / $499-max-loss spread at the page boundary
   (short 607–621 vs spot 767; the 0.13Δ short belongs at ~755, which is
   exactly where 09-04's plans landed via the sparser Monday-expiry chain).
   The same truncation explains GLD/XLF/TLT dying in spread_builder with
   "no viable spread plan" every single cycle — D21's universe expansion has
   been silently non-functional for the dense-chain half of the universe.
   The judge spent attention correctly rejecting the SPY junk every cycle;
   the shadow book wasted 3 virtual positions on it.

2. **Judge (class b) — stacking decisions are noise, ≥3 contradictions
   today.** Cycle 133 abstained on XLK (strength 0.346, ~24% credit/risk,
   1 open spread: "not strong enough conviction to justify deliberately
   doubling down"); cycle 134, thirty minutes later with near-identical
   facts (0.35, ~25%, 1 open), took it ("justifies concentrating"); cycle
   135 then added a *third* XLK spread on top of $837.50 already held.
   Identical facts, opposite decisions — the prompt's stacking guidance is
   a soft "prefer... by default" with no deterministic rule, and the $ caps
   don't bind (20% of equity ≈ $19.8k vs XLK's $1,273). Not touched tonight
   (one theme per night); see proposal below.

**Changes (theme: un-truncate the chain; spread_builder.py + tests).**
- `_fetch_contracts` now pages: `limit` 100 → 500 and follows
  `next_page_token` via `page_token` (REST-verified param name, see
  lab_real_prices.py; NOT verified against alpaca-mcp-server 2.3.0's tool
  schema — so both are guarded: a rejected `limit=500` retries the exact
  legacy call, a rejected `page_token` degrades to the pages already
  fetched with a loud log line. Never worse than today's behavior.)
  Page cap 8 bounds a runaway cursor.
- Snapshot load stays bounded: deltas are computed in-process, so the
  builder now shortlists the 20 nearest-to-target-delta OTM strikes (plus
  each one's snapped long leg) *before* fetching quotes, instead of
  quoting every contract of the expiration (a fully-paginated SPY
  expiration would have been a 300-symbol snapshot call). Long-strike
  snapping is factored into `snap_long_strike()`, semantics unchanged.
- `tests/test_spread_builder_pagination.py` (5 tests): dense-chain page-1
  truncation must paginate and land the short near the delta target (pins
  today's SPY shape); `page_token` rejection degrades to page 1; `limit`
  rejection retries legacy 100; snapshot request ≤ 2×shortlist symbols;
  runaway cursor stops at the page cap. Existing OTM-guard tests
  desk-checked against the new flow — chosen strikes unchanged.

**Watch tomorrow.** (1) `state/mcp_server.log` + bot.log for the two
fallback warnings — if "pagination failed" appears, the MCP tool rejects
`page_token` and the fix is running in legacy mode on dense chains; that's
the signal to bump alpaca-mcp-server (team call, pinned dep). (2) SPY
candidates should now show strikes ~750s with real credit, and GLD/XLF/TLT
should start reaching the menu (or die honestly at liquidity/vol stages) —
the funnel journal will say which. (3) XLK: three live bull puts
(182.5/177.5 ×2, 185/180) + XLE bear call + carried QQQ 705/700; if XLK
gaps down, that's ~$1,273 max loss on one name — the stacking pattern's
cost made real.

**Proposals (not touched tonight).**
- *Stacking rule for the judge* (next night's candidate theme, via
  tune-reasoner-prompt): a deterministic policy — e.g. "never a third
  spread on one underlying; a second requires strength ≥0.30 AND
  credit/max_loss ≥15%, cited" — would have kept 133/134/135 consistent
  in either direction. One more day of journal evidence makes it a ≥2-day
  pattern under the analyze-regret bar.
- *Post-close snapshots recorded SPY at 373.0* (20:00/20:30Z rows,
  vs 766 intraday) — a bad after-hours quote flowing into
  `account_snapshots.spy_price`. Display/telemetry only, but worth a
  sanity clamp when the team touches record_snapshot.py.

## 2026-09-07 evening (Labor Day — no trading; eve of post-hackathon re-entry)

**Evidence: none, and that's the finding.** Market closed all day (weekend +
Labor Day); all 12 cycles skipped, zero candidates, zero opens in any book.
Ablation and regret tables are byte-identical to what I classified on 09-04
(30 drops, 4 marginally positive +$29.6 vs −$924.9 aggregate) — per
analyze-regret: no new observations, no pattern, no selection or pipeline
change justifiable tonight.

**Verdict on the 09-04 watch items.** (1) Entry block: HELD — no new spread
appeared anywhere; morning cycles journaled the contest skip with zero
candidates and zero shadow opens. Weak test though: the market never opened.
(2) The two carried spreads (QQQ 705/700 bull put, XLE 65/70 bear call, exp
09-14) were never force-closed — "pending, market closed" all weekend — and
now won't be, because **the team extended `CONTEST_END_UTC` today ~17:58Z**
(inferred from the journal: cycles ≤17:30Z say "contest deadline", the
off-grid 17:58Z manual run and everything after say "Market is closed", and
`in_contest_close_window` never un-latches on its own; I verified only that
`.env` sets the key, not its value). Those two spreads re-enter normal
profit-target/stop management at tomorrow's open, DTE 6.

**State change I did not make but must flag: Roadmap v2 W1 is live.** Five
team commits (protections Gate 0, content-hash reasoner cache, idempotent
open order ids, real-price lab layer) run for the first time with entries
enabled tomorrow. Pre-flight desk-check of `protections.py` against current
journal data: stop_streak (24h window — last stops 09-03) quiet, cooldown
(90 min) quiet, drawdown (~0.02% vs 3% cap) quiet, **but the low_profit lock
WILL fire for QQQ**: trailing-7d realized ≈ −$626 (09-02/03 stop cluster +
09-04 churn) < −$300 floor. Expect QQQ rejected at `stage: "protections"`
Tue–Wed; it ages out ~09-10 15:30Z (stops leave the window), fully by 09-11.
That is the gate working as designed on losses whose causes were already
fixed (book-aware judge 09-02, entry/exit symmetry 09-04) — do not "fix" it.

**Change (one small theme: dormant-day journals must name the operative
reason).** Today's misattribution was my own 09-04 edit: I put the
`close_window` branch above `market_open`, so holiday cycles claimed "any
spread opened now would be force-closed" when nothing could trade at all —
it cost real analysis effort tonight to disentangle, and tomorrow the same
ladder would have mislabeled protections-vs-closed days. Extracted the
ladder into pure `bot._skip_reasoning()` with precedence: options-level
alarm → market closed → blackout → protections → contest window. Display
only — the trade-gating `if` (which requires ALL conditions) is untouched.
`tests/test_skip_reasoning.py` (5 tests) pins the precedence, including
today's exact case.

**Watch tomorrow (first live day of v2).** (1) QQQ rejected by low_profit
with the ≈−$6xx figure in the reason — if it's NOT rejected, protections
aren't wired the way I read them. (2) Reasoner cache: repeated identical
menus should journal "(facts unchanged since … — decision reused)" — check
the reused reasoning still cites facts sanely. (3) The two carried spreads
managed normally; no contest force-close should fire. (4) First real menus
since 09-04: shadow/menu books repopulate — regret analysis has data again.

**Proposals (not touched).** Still open from prior nights: per-spread cycle
rows (bot.py records one cycle per opened spread), `closed_force` status for
force-closes. New: with `lab_real_prices.py` in, the L3b ADX-gate hypothesis
from 09-01 can finally be adjudicated on real option bars — one team-run
`python backtest_lab.py` decides it; the variant is still dark in live code.

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
