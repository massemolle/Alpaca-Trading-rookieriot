# Alpaca Options Credit-Spread Agent — One-Pager

*Framing for judges: an auditable constrained-agent experiment on paper capital.
Not a claim of statistically proven LLM alpha or a universally optimal options
strategy. Replace bracketed placeholders with live numbers before final submit.*

## AI logic

- **Universe (frozen for judging):** liquid index ETFs only — default
  `SPY,QQQ,IWM` via `UNIVERSE_TICKERS` / `UNIVERSE_MODE=etf`. Single names stay
  off until earnings / ex-dividend protections exist.
- **Signals:** swing long/short only — **neutrals are rejected** (never mapped
  to a bear call by accident).
- **Structure:** credit verticals (bull put / bear call), short-leg target
  **0.17 model-delta**, **$5** width, **10–21 DTE**, **50%** profit target,
  **2×** stop — contest heuristics, not claimed optima. No further in-sample
  parameter search before Monday.
- **Vol filter:** realized-vol percentile proxy for IV rank (see `VolatilityFilter`).
- **Decision layer:** LLM selects from a **single immutable, risk-approved
  menu**; hard-capped to remaining concurrent slots. Same menu feeds mechanical
  and random shadow policies (`selector.mechanical_score` =
  `strength × credit / max_loss`).
- Autonomous calls this week: [N] → trade / [N] abstain / [N] gate-blocked —
  paste 2–3 real `reasoning` strings from `cycles`.

## Risk gates (quantity-aware)

- Size contracts **before** final approval; gates use
  `max_loss_per_contract × contracts`.
- Max loss per spread: 2% of equity; daily loss breaker −3%; max concurrent 5;
  concentration and buying-power checks in `pretrade_gate.py`.
- Default **`MAX_CONTRACTS_PER_SPREAD=1`** for Monday until fills are observed.
- Missing quote timestamps **fail closed**; entries use **bounded limit** prices
  with idempotent `client_order_id`; pending → filled only after broker confirm.
- Broker↔DB **reconciliation** every cycle; unexplained mismatch blocks entries.
- Force-close near expiry / contest deadline: verified RTH close workflow
  (reconcile → limit close → confirm / retry), not a blind market dump.

## Experiment integrity

- LLM / mechanical / random share eligibility, risk budget, and synthetic mid
  fills for attribution; **real broker fills** reported separately (slippage).
- Dashboard: realized vs unrealized per policy + sample size, abstention rate,
  gate-block rate, credit slippage.
- Offline lab: append-only `lab_trades` / `lab_summary` with `run_id`.

## Alpaca infrastructure

- Options reads/orders via [Alpaca MCP](https://github.com/alpacahq/alpaca-mcp-server).
- No broker Greeks on this feed → BS delta with realized-vol proxy; quote IV is
  **diagnostic only** (`iv_diagnostic.py`) until promoted after dry-run evidence.
- Schedule: `run_options_cron.sh` (flock + non-zero exit on failure).

## Results (fill from the real account)

- Starting equity: $100,000 ([date]) → Ending: $[X] ([date])
- Spreads: [N] opened / [N] profitable / [N] loss / [N] still open
- Account ID: [required for judging]

## Honest scope notes

- One-week N is underpowered — case study, not proof.
- Do not claim unconditional VRP edge, 0.17δ optimality, or LLM alpha over
  mechanical baselines without holdout evidence.
- Unresolved risks remain explicit in `PREMORTEM.md` (assignment, ex-div, etc.).
