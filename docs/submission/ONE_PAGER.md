# rookieriot — an options agent with receipts
*lablab.ai × Alpaca AI Trading Agents Hackathon · paper account PA34CFYP0MIZ · all data live at https://alpaca-trading-rookieriot.vercel.app*

## What it is
An autonomous credit-spread trader on liquid index ETFs where **code holds all the risk
authority and the AI holds all the judgment** — plus the instrumentation to prove which
one is earning its keep.

## Design: capability only where verification exists
- **Deterministic funnel**: screening → momentum signals → trend & vol filters →
  strike construction → risk gate. Every rejection journaled per stage, per ticker.
- **The judge (Claude Opus 4.8)**: sees only pre-approved candidates as cited facts
  (`{fact_id, value, source, timestamp, quality}`), may pick or abstain, must cite
  every number it uses. Stateless by design — each decision independently auditable.
- **Second gate** re-verifies with fresh quotes after selection; mechanical exits
  (50% profit target, 2× stop); macro blackout windows (JOLTS, NFP); broker↔DB
  reconciliation blocks entries on any mismatch. Defined-risk verticals only.
- **The engineer (Claude Fable 5)**: nightly session with full code access, bracketed
  by a hard gate — compile + 85 tests + forced simulation cycle, or full auto-revert.
  Changes must carry falsifiable predictions the next session verifies.

## Evidence layer (the actual submission)
- **Live ablation**: every cycle, a mechanical rule and a random policy trade the
  identical menu. Result this week: **AI −$620 vs rule −$1,101 vs random −$672**
  [FINAL: update after Friday flatten] — the AI's edge was *refusal*: it declined the
  broken deep-ITM trades and noise-grade signals its baselines swallowed.
- **Regret tracking**: every unpicked candidate virtually filled and marked — the AI's
  drops were net negative all week (zero profitable regret).
- **Audit page**: every decision's verbatim cited reasoning, AI-vs-rule badges, every
  gate rejection, and the nightly engineer's full trail — REVERTED nights included.
- **Measured strategy**: 16-month component ladder (raw −$1,967 → +trend −$1,069 →
  +vol +$1,289; rule +$1,301 vs random +$1,092±160), proxy-pricing caveats printed.
- **Execution honesty**: est vs filled slippage on every trade, SPY benchmark overlaid
  on our own equity curve.

## What the self-repair loop actually did (4 nights)
| Night | Found | Outcome |
|---|---|---|
| 0 | (its change broke 3 tests) | **auto-REVERTED by the gate** — shown publicly |
| 1 | vestigial $300 price cap silently excluded SPY/QQQ from screening | fixed + funnel observability |
| 2 | trend filter computed ADX, never used it | fixed as dark switch, lab-tested, then enabled |
| 3 | judge was blind to its own book (six identical spreads) | book-awareness facts; predicted duplicates →≤2 |
| 4 | builder emitted impossible ITM "credit spreads" on stale quotes | fixed; **verified night-3 prediction: duplicates = 0; cancelled its own escalation** |

## How it's built (all components in production, built in 6 days)
**Python engine** (cron, one decision cycle / 30 min; 85 tests incl. chaos suite) →
**Alpaca MCP** for every option quote and multi-leg limit order, dedicated paper account →
**Supabase Postgres** as the single source of truth (trades, decision journal, three
virtual books, nightly-engineer trail) → **Next.js dashboard on Vercel** (auto-deploys
each push; `/`, `/audit`, `/lab`) → **Telegram Mini App**: the entire dashboard one tap
away inside the chat bot — the agent in your pocket. Two Claude models split the work:
**Opus 4.8** judges trades by day (stateless, cited facts only); **Fable 5** engineers
by night behind the auto-revert gate. Feature-by-feature build: every layer landed with
its tests before the next began, fully reproducible from the repo.

## Honest scope
Four trading days of P&L is statistical noise and we say so on the dashboard. We do not
claim proven alpha. We claim a complete, working answer to the question that matters
before anyone trusts an AI with money: *can you verify what it did, why, and whether
the AI — not luck, not the pipeline — is responsible for the outcome?* Ours, you can.
Every claim above is one click deep on the live dashboard.
