# Alpaca Options Credit-Spread Agent

Submission for lablab.ai's **Alpaca AI Trading Agents Hackathon**
(28 Aug – 4 Sep 2026).
Team **rookieriot**: Alex ([@Alejdro83](https://github.com/Alejdro83)), Guillaume ([@massemolle](https://github.com/massemolle)), [third teammate].
Decision log with evidence for every architecture choice: [PLAN.md](PLAN.md) · failure-mode checklist: [PREMORTEM.md](PREMORTEM.md).

An autonomous agent that trades **credit vertical spreads** on liquid index
ETFs (default SPY/QQQ/IWM): a bull put when swing signals are long, a bear
call when short — neutrals are rejected. Defined-risk from open, sized and
gated by explicit quantity-aware rules the LLM cannot override. Judged as a
**constrained-agent experiment** with a live mechanical/random ablation, not
as proven LLM alpha.

**Live dashboard**: https://alpaca-agent-dashboard.vercel.app (also opens
as a Telegram Mini App via [@Alpaca_alejdro_bot](https://t.me/Alpaca_alejdro_bot) — same page, same code, either way).

## Why this design

- **Screening/signals**: vendored, unmodified, from a real trading system
  (`trading_bot/` on the author's own infrastructure — 400+ live paper
  trading cycles before this hackathon existed) — day/swing multi-horizon
  signal generation, EMA50/200 + ADX trend filtering, liquid-universe
  filters. This project reuses its *underlying selection* logic and
  translates the resulting direction into an options structure instead of
  an equity order.
- **Options execution — 100% via [Alpaca's official MCP
  server](https://github.com/alpacahq/alpaca-mcp-server)** (`mcp_client.py`,
  `spread_builder.py`, `executor_mcp.py`) — every chain lookup, quote, and
  order placement goes through MCP tool calls, never the raw SDK.
- **Delta computed in-process, not broker-supplied** (`black_scholes.py`)
  — verified live against the real account that real-time OPRA options
  data (needed for Alpaca's own Greeks) requires a paid Algo Trader Plus
  subscription; the free/paper `indicative` feed returns quotes with no
  Greeks at all. Rather than degrade to picking strikes by a fixed dollar
  distance, delta is computed with a standard closed-form Black-Scholes
  formula, using the same realized-volatility estimate the entry filter
  already computes as the implied-vol proxy — labeled as a proxy
  throughout, not overclaiming real IV.
- **Risk gates** (`risk_gate.py`, `pretrade_gate.py`, `sizing.py`,
  `reconciler.py`) — quantity-aware max-loss / BP / concentration checks,
  missing quote timestamps fail closed, broker↔DB reconciliation blocks
  entries on mismatch, bounded limit orders with idempotent client IDs and
  pending→filled tracking.
- **Autonomous decision layer** (`llm_reasoner.py`) — among whatever
  survives the gate, an LLM picks which spread(s) to open; hard-capped to
  remaining budget. Same immutable menu feeds mechanical + random shadows
  (`selector.py`, `shadow_book.py`).
- **Deployment**: `run_options_cron.sh` (flock + non-zero exit on failure)
  every ~30min during market hours.
- **Dashboard**: Next.js app (Telegram Mini App capable) — equity curve,
  spreads, cycle reasoning, ablation with abstention / gate-block / slippage
  meta.
- **Go-live**: keep `DRY_RUN=true` until the Monday rehearsal in
  [`docs/runbooks/monday.md`](docs/runbooks/monday.md) passes; default
  `MAX_CONTRACTS_PER_SPREAD=1`.

## Running it

```
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # dedicated hackathon Alpaca account; set DRY_RUN=true
python smoke_test.py SPY   # MCP + options + ~$100k account
DRY_RUN=true python bot.py # one dry cycle
python -m pytest tests/ -q
python verify_backtest.py
python iv_diagnostic.py    # offline IV diagnostic (no live strike change)
```

Scheduled execution: `run_options_cron.sh` (shared `state/bot.lock` with
`emergency_flatten.py`). See `docs/runbooks/monday.md` for go-live.

## Files

| File | Role |
|---|---|
| `bot.py` | Main cycle: manage open spreads → screen → risk-gate → LLM decide → execute |
| `spread_builder.py` | Signal → concrete strikes/expiration via MCP option contracts + quotes |
| `black_scholes.py` | Self-computed delta (no broker Greeks available — see below) |
| `risk_gate.py` | Hard, non-negotiable risk checks, incl. force-close-by-contest-end |
| `llm_reasoner.py` | The autonomous decision step among risk-approved candidates |
| `executor_mcp.py` | Opens/closes spreads, exclusively via Alpaca's MCP server |
| `mcp_client.py` | Thin async wrapper spawning `alpaca-mcp-server` over stdio |
| `db.py` | Writes agent state to Supabase for the dashboard |
| `config.py` | All tunables, env-overridable, defaults explained inline |
| `screening/`, `signals/` | Vendored from `trading_bot/` — unmodified |

## Parameter optimization pass (`backtest_optimize.py`)

Run once, 2026-08-27, before the first live trading day. Reuses the REAL
signal-generation logic (a documented frozen port of `signals.swing`'s
per-symbol scoring, since that function fetches live data internally and
can't be pointed at an arbitrary past date), the REAL `TrendFilter`, and
the REAL volatility-percentile filter against REAL historical daily bars
(`trading_bot/backtest/data.py`'s `HistoricalDataLoader`, unmodified) — but
simulates spread economics with Black-Scholes theoretical pricing on the
same realized-vol proxy the live bot uses, since real historical option
chain prices aren't available on this account (same limitation as the live
bot's own delta calculation — see below). This compares our own parameter
choices against each other on one consistent, honest proxy; it is **not**
a market-realistic options backtest, and it doesn't simulate the
concurrent-spread portfolio cap or the LLM selection step.

Result on a 12-symbol liquid basket over ~2 years (104 real entry events):
the 10-21 DTE window (the 2026-08-26 research pass) held up well against a
7-14 alternative — a large, sign-flipping difference (7-14 went net
negative in several combinations), not a marginal one, so this conclusion
survives the caveat below. `short_leg_target_delta` initially looked like
it should move 0.17 → 0.20 (win rate 80.8% vs 78.8%), but a follow-up
sanity pass against synthetic cases (see `verify_backtest.py`-equivalent
checks run inline, 2026-08-27) found the strike-selection step (round the
Black-Scholes-implied strike to the nearest $1, an already-disclosed proxy
for a real listed-strike ladder) carries real, quantified error — up to a
34-47% relative delta miss at the production 15-day DTE midpoint for the
basket's lower-priced names (e.g. CMCSA, ~$35-45). That's the same order
of magnitude as the 0.17-vs-0.20 difference itself, so that specific
result is **not trustworthy** and was reverted — `short_leg_target_delta`
stayed at **0.17**. Recorded here rather than quietly fixed, since the
first version of this note (now corrected) stated the 0.20 bump with more
confidence than the underlying check actually supported.

## Honest scope notes

- **No broker-supplied Greeks.** Verified live: `feed=opra` needs paid OPRA;
  free `indicative` has no `greeks`. Delta via `black_scholes.py` + realized-vol
  proxy. Quote IV (`iv_diagnostic.py`) is shadow-only until promoted.
- **ETF core only** for the judged book; broad equity scrape remains behind
  `UNIVERSE_MODE=broad` for offline experiments.
- **`open_interest` is frequently `null`** — liquidity leans on bid-ask when OI
  is missing.
- LLM may abstain; it cannot trade a failed gate. Shadows use the same menu and
  aggregate max-loss budget; virtual fills are synthetic mid, not broker fills.
- Frozen parameters (0.17δ, 10–21 DTE, $5, 50%/2×) are contest heuristics — do
  not present as proven optima. No critic/extra LLM/crypto sleeve this weekend.

## Weekend hardening (landed)

- Quantity-aware sizing + pretrade gates; limit opens/closes; fill/pending
  states; broker reconciliation; monitor mark ×100; market-hours ordinary
  closes; cron fail-exit; unified selector; lab schema; ETF freeze + neutral reject.
