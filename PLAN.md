# Alpaca AI Trading Agents Hackathon — Plan & Decision Log (v3)

Source of truth for architecture and scientific approach. v2 incorporated an external evidence review (2026-08-27); v3 (2026-08-28) records the team merge. Update when a decision changes; note why.

## D16 — Team merge (2026-08-28)

Guillaume joined a team with Alex ([alpaca-options-agent](https://github.com/Alejdro83/alpaca-options-agent)) + one more. **Alex's repo is the adopted trading core** — reviewed and security-passed 2026-08-28: MCP-only execution, hard pre-LLM risk gates, LLM abstains on any failure, shadow-selector decision journal, atomic mleg orders with client IDs, live dashboard. His codebase *empirically resolves our D0 spike*: free/indicative feed has **no Greeks at all** (opra 403s without paid plan) → he self-computes Black-Scholes delta with a realized-vol proxy; `open_interest` often null even on SPY; MCP mleg works (string-typed `qty`); a real phantom-position incident occurred and was fixed fail-loud — validating D3/D8 empirically.

Plan: Alex's tree stays untouched (never reorganize a running trader mid-contest); Guillaume ports the science layer: **pre-trade gate #2**, **counterfactual-P&L ablation + random baseline**, **SPY attribution**, **chaos tests**. Open team decisions: add SPY/QQQ to the universe (supported by Alex's own delta-proxy error analysis on low-priced names), reasoner-model A/B in the shadow journal, third teammate's role. Sections below predating the merge describe our original solo architecture — still the reference for the science layer; superseded where Alex's working code decided otherwise.

## Hackathon facts

- Aug 28 → Sep 4 2026, deadline Sep 4 15:00 UTC (11:00 ET, mid-session). [Page](https://lablab.ai/ai-hackathons/alpaca-ai-trading-agents-hackathon)
- Rules as understood: Alpaca Trading API + MCP server or CLI required; **options trading mandatory**; final run on a **fresh dedicated paper account**; paper trading only. ⚠ Not every rule independently verified on the public page — keep an exact link or Discord quotation for each rule before relying on it.
- Judging: P&L, technology implementation, creativity/originality, presentation.
- Trading days: Fri 28, Mon 31 → Thu 3, Fri 4 morning. Sat–Sun closed (build/test window).
- Alpaca: stocks/ETFs/options (multi-leg, Level 3 spreads; options enabled by default on paper accounts — **verify actual account fields, don't assume**) + crypto spot 24/7 (no crypto options).

## Core hypothesis (falsifiable)

> Given an identical, risk-filtered candidate menu, can timestamped unstructured context improve option selection over a structured-only selector, without increasing predefined risk?

We do NOT claim "LLM agents produce trading alpha" — the literature does not support that (see D3a). The safety architecture is evidence-backed; the profitability thesis is the experiment. With ~10–15 decision cycles this is an **exploratory case study**, not proof.

## D0 — Feasibility spike (BLOCKING, before full build)

`scripts/spike_feasibility.py` must pass before scaffolded modules get implementations:

1. Read paper account; record actual options approval fields.
2. Fetch an option chain with quote timestamps, IV, Greeks; record feed type + quote age.
3. Submit and cancel one two-leg paper order (REST path). Separately, on the first market session, test multi-leg through the actual MCP client (known open issue: multi-leg array transmission failing in at least one Claude MCP client, Jul 2026).
4. Reconcile broker positions, orders, activities/fills.
5. Record every raw response as a committed test fixture (`fixtures/broker_responses/`).

Status: **blocked on credentials** (local env vars only; `.env.example` provided; never pasted into chat).

## D1 — Design B: "code generates, LLM selects" — with TWO gates (DECIDED, revised)

```
generate candidates (code) → eligibility gate (code) → LLM selects/abstains
  → re-fetch broker state + quotes (code) → pre-trade gate (code)
      → valid: submit idempotently → reconcile
      → invalid: abstain + log
```

1. **Perception (code)** — account state, prices, chains, IV, Greeks, news, calendar → typed market packet. Every fact carries provenance (D10).
2. **Candidate generation (code)** — deterministic modules per structure (credit spread, debit spread, collar, straddle), pre-priced: max loss/gain, break-evens, DTE, scenario grid (D9).
3. **Eligibility gate (code)** — hard limits filter the menu before the LLM sees it.
4. **Judgment (LLM)** — selector picks by candidate ID from the menu, sizes within bounds, or abstains. Schema-validated JSON; rationale must cite packet fact IDs.
5. **Pre-trade gate (code)** — AFTER selection: re-fetch account/orders/positions/quotes, recalculate risk on current state, reject or resize if anything changed. The LLM never argues with either gate.
6. **Execution (code)** — idempotent submit (client order ID), full order state machine (D8), reconcile broker response.

## D2 — Roster (REVISED: minimal LLM surface)

**Deterministic modules (no LLM, no personality):** candidate generators per option structure; both risk gates; scheduler; monitor; reconciler; attribution.

**LLM roles (3 only):**
- **Analyst/selector** — packet + retrieved memories → regime + vol view → menu selection or abstention.
- **Independent critic** — sees packet + chosen candidate **without the selector's rationale** (reduces anchoring); outputs strongest objections; disposition logged. Run critic-on/off as an ablation — its value is unproven.
- **Evening reflector** — learns from **process errors only** (execution failures, stale data, invalid assumptions), never infers new strategy from a few trades.

**Capital allocation:** **fixed risk budgets per sleeve, set before the run.** No performance-based reallocation on 5-day returns (that's noise — our own principle). Contest mechanism, if kept, is shadow-only or tiny capped changes; we do not claim short-term P&L reveals sleeve superiority.

Explicitly NOT building: fine-tuned models, full backtesting engine, >3 sleeves, LLM strategist "agents".

## D3a — What the literature supports (corrected verdicts, v2)

Survey context: agentic-trading research is immature — of 19 primary empirical studies, 2 had extractable time-consistent splits, 1 an explicit transaction-cost model, 17 not peer-reviewed. **No dependable consensus that LLM agents produce alpha.**

| Claim | Verdict | Our use |
|---|---|---|
| Bull/bear debate beats single opinion (TradingAgents) | Overstated — no equivalent single-agent ablation | Keep critic, but treat as ablation, blind to rationale |
| Layered memory beneficial (FinMem) | Plausible, narrow (mostly TSLA ablation) | Light memory; no "small+memory beats large" claim |
| Capital flows to winning sleeves (ContestTrade) | Unsupported at 5-day horizon (6-mo A-share backtest) | Fixed budgets; contest shadow-only |
| Dual-level risk control (FinCon) | Inspiration, not replication (CVaR alerts + training-time prompt optimization) | Code gates + process-only reflector |
| Pre-digested facts > raw series (Agent Trading Arena) | Shows charts > plain-text series; doesn't test fact packets | Keep as engineering choice, cite precisely |
| Constrained action space (constrained-agent paper) | Supports auditability, not proven performance | Keep menu/DSL for auditability |
| Explicit abstention (AgentAbstain) | Necessary, NOT solved by prompting — best agent 59.5% correct on act/abstain | **Code enforces** abstention on stale data, tool failure, inconsistent state |
| Broker as sole state truth (TradeTrap) | Strongly supported (phantom portfolios) | Re-fetch every cycle; LLM memory ≠ fact |
| Attribution + leakage control (KTD-Fin, Profit Mirage) | Strongly supported | Shadow benchmarks, ablation, leakage-aware replay |
| Critic prevents rubber-stamping (MAST) | Sensible, unvalidated as trading intervention | Blind critic + on/off ablation |

## D3 — Failure modes → mitigations

| Failure | Mitigation |
|---|---|
| State hallucination / phantom positions | Broker API sole source of truth; re-fetch each cycle |
| Hallucinated numbers propagate | All numbers from tools; rationale must cite fact IDs; no un-sourced numbers |
| Temporal errors | DTE, expiries, market hours, event-before-expiry computed in code |
| Overconfidence / action bias | Abstention enforced in code, not just prompted; "no trade" logged as first-class |
| Rubber-stamp validation | Blind critic; every agent justified; MAST-informed |
| Returns noise vs systematic failure | Risk-first: chaos tests, pre-mortem, guards over returns-chasing |
| Training-data leakage | Live week is clean; replays = plumbing tests on recent obscure windows only |
| Prompt injection via news | News is untrusted input (D10): structural separation, claim extraction, injection chaos tests, news tools never get execution permissions or risk-config influence |

## D4 — Cadence & tokens

- Every few min, zero LLM: code monitor — stops, fills, bound breaches, **assignment/exercise polling** (don't rely on websockets alone).
- Every 30–60 min: one cheap small-model "material change? yes/no" call; yes → escalate.
- 2–3×/day full pipeline: open, midday, ~1h before close.
- Budget: measure per-cycle cost after spike, then set tiers.

## D5 — Build & test around the closed market

- Injectable clock from line 1; replay harness on recorded/historical data (shadow mode); dry-run flag (log orders, don't place).
- Replay = plumbing/behavior test only, never performance estimate (leakage).
- Crypto weekend sleeve: **optional** — tests generic order plumbing only, NOT the critical multi-leg options path.
- Chaos tests: stale quote, timeout, malformed chain, unexpected position, prompt-injection payloads → degrade safely (abstain + alert).
- Accounts: dev account for testing; official fresh account started by Mon 31.

## D6 — Team & system shape

- Solo (Guillaume). Cut criteria (D11) binding.
- `backend/` Python modular monolith (domain / application / ports / adapters — see repo tree); `frontend/` read-only dashboard.
- **Admin controls** (authenticated endpoint or local CLI, NOT public dashboard): pause decisions, cancel open orders, flatten positions, disable sleeve, switch to dry-run, **global kill switch** on stale/corrupted state. Kill switch = operational maturity, not weakened autonomy.
- Universe: start SPY/QQQ; single names only if event sleeve justifies.

## D7 — Alpaca engineering facts (from review; verify in spike)

- **Free options feed is indicative**: delayed trades, modified quotes; OPRA needs paid plan. Every candidate carries feed type + quote age; stale/indicative affects eligibility.
- **No historical IV/Greeks endpoints** — snapshots only. "IV rank" requires storing our own snapshots over time, another source, or computing historical IV ourselves. Until then: don't cite IV rank as a fact.
- **MCP multi-leg open issue** (Jul 2026): array transmission failing in ≥1 Claude MCP client though REST worked. Test our exact client on day 1.
- **No equity legs in MLeg orders** → collar is non-atomic (stock + option legs separately): handle leg imbalance.
- **Paper trading omits** market impact, queue position, latency slippage, price improvement, fees → contest outcome, not scientific evidence.
- **Forced liquidation deadline** before Sep 4 15:00 UTC; avoid same-day-expiry / pin / assignment exposure near the end.

## D8 — Order state machine & idempotency

States: proposed → risk-approved → submitted → acknowledged → partially-filled → filled | cancel-pending → cancelled | rejected | replaced | **reconciliation-required**.
Every submission has a client order ID. On timeout: **never blindly retry — query Alpaca first** to learn whether the original order exists. Options lifecycle handled explicitly: expiration/pin risk, early assignment, exercise, ex-dividend for short calls, delayed paper activity reporting, multi-leg close semantics, partial fills / temporary leg imbalance, no stop orders on some multi-leg structures, deadline mid-session.

## D9 — Pre-trade gate contents & scenario risk

Final gate recalculates: buying power; current positions + open orders; quote freshness; candidate price + max loss; portfolio Greeks; concentration; duplicate exposure; data-feed quality; time remaining before deadline/expiry.
Greeks are local approximations — also evaluate a **scenario grid** per candidate: underlying −5/−3/−1/+1/+3/+5%; IV −10/−5/0/+5/+10 vol points; time now/+1d/near-expiry; correlated SPY/QQQ moves. Record **worst scenario loss** alongside theoretical max loss.

## D10 — Data provenance & security

Every packet fact: `{fact_id, value, as_of, source, feed, quality, derivation}`. LLM rationales cite fact IDs, never repeat unsupported numbers.
News/webpages/MCP responses are untrusted: structural separation of instructions from content; extract claims/timestamps/entities/URLs before the LLM sees them; never concatenate raw pages into prompts; injection examples in chaos tests; news tools can never acquire execution permissions or alter risk config.

## D11 — Cut criteria (solo survival)

- Multi-leg execution not reliable after first market session → simplify structures.
- Event data not reliable by Mon 31 → cut the event sleeve.
- Dashboard not reading real persisted decisions by Tue 1 → cut visual embellishments.
- No new agents after Wed 2.
- Thu 3 = stabilization + presentation only.

## D12 — Directions considered and REJECTED (2026-08-27, after trading-desk feedback)

| Direction | Why rejected |
|---|---|
| Forex, futures | Not offered by Alpaca (US stocks/ETFs/options/crypto only) |
| Cross-exchange arbitrage | One venue, one account, delayed indicative options feed. Worse: paper simulator fills at possibly-stale quotes, so "arbitrage" P&L would be fabricated — gaming the simulator, recognizable by Alpaca judges. We will state explicitly that our P&L contains none of this |
| Illiquid single-name options | Live: wide spreads are the market maker's edge — we'd pay it both ways ("get eaten"). Paper: simulator fills illiquid names at prices unavailable live → measured "edge" is an artifact. Corollary: SPY/QQQ-only universe CONFIRMED (deepest markets = most honest paper fills) |
| News-speed trading | Public information is priced in within seconds by pros (desk feedback). We never claim reaction-speed edge; unstructured context feeds *selection quality*, not speed |
| Same-day-expiry (0DTE) | Pin/assignment risk near deadline (already D7/D9) |
| General agent frameworks as the trader (e.g. Nous Hermes Agent, considered 2026-08-28) | Open-ended code execution + web access + broker credentials = the free-form authority our whole design exists to remove (D1 bounded menu, D10 injection isolation). Its skill-writing "learning" is unvalidated self-modification from tiny samples — exactly what D15's statistical promotion gate forbids. Possible niche as ops/alerting only; a plain webhook is simpler |

**Edges we DO claim (honest version):**
1. **Volatility risk premium**: options systematically price above subsequently realized vol; harvesting it with defined-risk credit spreads needs no speed or private info — compensation for tail risk, sized accordingly.
2. **Operational survival**: the contest is won on mechanics (assignment handling, sizing, no phantom state). Most teams blow up operationally; we're engineered not to.
3. **Manual Bloomberg/Reuters morning brief**: terminal access can't be piped in, so Guillaume enters 3–4 distilled facts each morning (IV vs realized, event calendar, positioning anomalies) as provenance-tagged input (`source: bloomberg_manual_brief`). Agent stays autonomous — it decides what to do with the brief. Higher-quality context than free-API scraping, no speed claim.
4. **AI consistency**: never bored, never revenge-trades, always documents. Breadth + discipline, not prediction.

## D13 — Capital, sizing, and crypto allocation

- **Think in risk budget, not capital.** Selling defined-risk premium consumes buying power as collateral; large cash balances are normal, not idle.
- Account $100k paper. Sizing so P&L is *legible*: risk per trade 1–2% ($1,000–2,000), daily loss stop ~3%, portfolio worst-scenario (D9 grid) capped ~10%.
- Target: +1.5–3% over the week with max drawdown < half the gain — a visible, steady equity curve. $5 of profit is invisible at this scale; so is 1-contract undertrading. Some teams will YOLO for +20%; we counter on risk-adjusted P&L + the other three judging criteria.
- **Crypto: ≤10% risk budget, possibly 0. Rejected 80/20.** Alpaca crypto is spot-only (no options hedge); BTC moves 3–5%/day, so a 20% allocation would swing the account ±1%/day on pure beta — drowning the options P&L we're trying to attribute. If kept: small BTC/ETH sleeve (~5%) for weekend liveness, clearly attributed as beta.

## D14 — Alpaca capability inventory (swept 2026-08-27)

Useful, not yet in plan: **news API** (Benzinga-backed, historical + websocket — candidate claim source); **screener/market-movers endpoints** (event-sleeve candidate discovery); **calendar & clock endpoints** (authoritative market hours for ClockPort — don't hand-roll); **corporate-actions API** (ex-dividend checks for short calls, D8); **websocket streams** for stocks/options data (monitor tier); **extended-hours equity trading** (pre/post market — options stay RTH; useful only for hedging the ETF core); **short selling** (enables synthetic structures; not needed v1); **fractional shares** (irrelevant); **bracket/OCO orders** (equities only — NOT multi-leg options, confirming D8's "no stops on spreads" handling).
Gotchas: **paper account reset wipes the equity curve — NEVER reset the official account** (add to runbook + admin-API guard); API **rate limit ~200 req/min** (fine at our cadence; monitor tier must budget it); PDT rules irrelevant at $100k; crypto has limited order types.

## D15 — Overnight strategy lab (STRETCH GOAL, 2026-08-27)

The 2026 frontier (FunSearch/AlphaEvolve lineage: QuantaAlpha, MadEvolve, AlgoEvolve, FactorMiner, XALPHA) is agents that *evolve strategy code*, not just judge trades. Our bounded version:

- Daytime: trade with **frozen** generators. Overnight: evolution loop mutates generator **parameters only** (delta bands, DTE windows, credit/width thresholds — never free-form code) and evaluates variants on the replay harness over historical options data.
- **Promotion gate is pure code**: variant replaces incumbent only on pre-registered out-of-sample criteria; losers run in shadow. No LLM discretion in promotion.
- Constraints: Alpaca historical options data starts ~Feb 2024 (short windows — report honestly); subject to D11 cut criteria; safe pipeline ships first; replay harness built evolution-ready (same harness, two consumers).
- Answers "anyone with Claude Code rebuilds this": the pipeline is reproducible; the agent-as-researcher demo ("here's the rule diff my agent derived Tuesday night + out-of-sample evidence") is the differentiator.

## Baseline anchoring (added 2026-08-27)

The no-LLM baseline in the ablation is not home-made: it follows **CBOE strategy-benchmark methodology** (PUT/BXM indices — published rules, ~30y track record, PUT ≈10.1%/y at lower vol than S&P). Claim upgrade: "the LLM tries to beat the industry-standard mechanical benchmark," and "the 30-year-old rule is still king" is a publishable negative result. Context for judges: public academic factors decay post-publication; risk premia (VRP) persist because they compensate risk — which is why the strategy survives being public, and why nobody (including competitors) has "the best algorithm."

## Science / evaluation

- **Verifiable decision record** (not "reasoning chain" claims): packet + menu hashes; fact IDs + provenance; model/prompt/schema versions; chosen + rejected candidates; critic objections + disposition; gate inputs/results; broker request/response/fills/reconciliation; subsequent outcome. Append-only.
- **Shadow ablation on every frozen menu** (pre-registered rules, horizon, pricing assumptions, risk budget):

| Policy | Purpose |
|---|---|
| Deterministic structured-only rule | Main no-LLM baseline |
| LLM without news/text context | Value of structured LLM reasoning |
| LLM with unstructured context | Core hypothesis |
| LLM + critic | Tests the critic |
| Random eligible candidate, matched trade rate | Sanity baseline |

- Metrics: risk-normalized P&L, drawdown, turnover, abstention rate, execution quality. Framing: exploratory case study.
- **SPY = synthetic shadow benchmark** (not capital-consuming). Options attribution additionally reports delta exposure, theta/vega changes, slippage where possible.
- `PREMORTEM.md`: each imagined failure → a guard or a test.

## D17 — Build-week schedule (agreed 2026-08-28 night; deadline Fri Sep 4, 15:00 UTC)

Baseline (Alex's, running): screening→signals→risk gate→LLM select→MCP execute, decision journal with shadow selector, dashboard/Mini App, claude_code reasoner (ours), cron every 30min, DRY_RUN on. Everything below is OUR layer, one small PR at a time; cut criteria D11 binding.

| When | Build | Feeds judging |
|---|---|---|
| **Sat 29** | **PR1 — pretrade gate hardening**: extract bot.py's `_pre_trade_check` → `pretrade_gate.py`; add re-fetch of account+open spreads at check time, concentration args (currently silently skipped post-LLM), intra-cycle open-count increment, buying-power floor; first pytest suite (fake MCP, no network) | Tech |
| **Sat 29** | **SPY attribution v1**: record SPY close with every snapshot; dashboard overlays normalized SPY vs equity ("skill vs market") | Presentation, Tech |
| **Sun 30** | **PR2 — shadow book / ablation P&L**: journal already stores llm_selected vs shadow_selected; add `shadow_positions` table (virtual fills at candidate credit), mark both books each cycle via MCP quotes → dashboard chart "Claude's picks vs mechanical rule, in $" | Creativity, Tech — the demo centerpiece |
| **Sun 30** | Replay of Fri's recorded cycle shapes through pretrade gate tests; PREMORTEM tick-off pass | Tech |
| **Mon 31** | Market open: **2 dry cycles → review journal ~17h Paris → flip DRY_RUN=false same day** (P&L needs the days); evening: reconcile bot.py with Alex's local iron-condor version (his live account traded condors; repo builds verticals — ask him to push or decide verticals-only) | P&L |
| **Tue 1** | **Morning-brief input** (D12 edge #3): `brief.md` the human writes from Bloomberg/Reuters each morning → injected into reasoner prompt as provenance-tagged context; journal records brief hash | Creativity |
| **Wed 2** | Chaos tests (stale quote, malformed MCP result, error-shaped success); **feature freeze** per D11; optional stretch ONLY if green: D15 parameter-lab shadow run | Tech |
| **Thu 3** | Stabilization + presentation: equity/attribution/ablation screenshots, 2-3min video, one-pager; scrub deferred identifiers (Open questions item 1); verify submission format requirements | Presentation |
| **Fri 4 AM** | Submit before 15:00 UTC; forced-close check on open positions (min DTE already ≥10 so no same-week expiries) | — |

Explicitly cut unless everything above is green early: D15 full evolution lab, multi-model reasoner A/B, event-straddle sleeve.

## D18 — No iron condors; instance divergence protocol (2026-08-28)

**Verticals only on our instance.** Guillaume's call, and the literature backs it rather than contradicting it: CBOE's 30y benchmark comparisons put put-writing strategies on top (BXMD 10.66%/y, PUT 10.13%/y) with the iron-condor index (CNDR) trailing; the volatility risk premium is concentrated in index puts, so a condor's short call adds rally risk for little extra credit. The repo's code already builds only verticals — we simply do NOT adopt Alex's local iron-condor evolution. Bear-call verticals stay allowed when the signal is genuinely bearish (directional trade, defined risk).

**Divergence protocol:** this instance (team repo `main` + this machine + the judged account) is ours; Alex experiments freely on his machine/branches — but **never trading the judged account while our cron holds it** (one live trader per account; his tests belong on a dev paper account). Comparison happens through artifacts, not shared state: decision journals, equity curves, and end-of-week attribution. Merges from his side come as reviewed PRs, not direct pushes to the trading path.

## Open questions

- [ ] Final scrub before submission (Sep 3–4): remove old-repo mentions in D16 and third-party identifiers (Gaussly, Agent Bazaar, /home/lab-master, dead Hermes link in README) — deferred 2026-08-28 to avoid touching working code mid-week
- [ ] Submission format — Guillaume asking lablab Discord / community@lablab.ai; capture exact quotes for each rule
- [ ] Spike results (D0) — blocked on local credentials
- [ ] MCP multi-leg path works in our client? (day-1 test)
- [ ] IV history source decision (own snapshots vs skip IV-rank facts)
- [ ] Earnings calendar Aug 28–Sep 4 → event sleeve go/no-go
- [ ] LLM tiers + daily token budget (after spike cost measurement)

## Key references

[Agentic Trading survey](https://arxiv.org/html/2605.19337v1) · [TradingAgents](https://arxiv.org/abs/2412.20138) · [FinMem](https://suchow.io/assets/docs/yu2024finmem.pdf) · [ContestTrade](https://arxiv.org/pdf/2508.00554) · [FinCon] · [KTD-Fin](https://arxiv.org/abs/2605.28359) · [TradeTrap](https://arxiv.org/html/2512.02261v1) · [Standard Benchmarks Fail](https://arxiv.org/abs/2502.15865) · [MAST](https://arxiv.org/pdf/2503.13657) · [Profit Mirage](https://arxiv.org/pdf/2510.07920) · [Constrained LLM agents](https://arxiv.org/html/2604.26747v1) · [Agent Trading Arena](https://arxiv.org/pdf/2502.17967) · [AgentAbstain] · [Alpaca MCP server](https://github.com/alpacahq/alpaca-mcp-server) · [Alpaca options docs](https://docs.alpaca.markets/docs/options-trading) · [Alpaca data plans](https://alpaca.markets/data)
