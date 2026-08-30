# Team rookieriot — options trading bot (lablab.ai × Alpaca hackathon)

Credit-spread trading bot: code generates candidates, an LLM selects or
abstains, two code risk gates bracket it. `PLAN.md` is the decision log —
read it before proposing architecture changes, log changes there.

## Layout
- `bot.py` — cycle orchestrator (cron every 30 min, US market hours)
- `signals/`, `screening/` — candidate generation; `spread_builder.py` builds vertical plans
- `llm_reasoner.py` — the selector LLM (system prompt + fact citations); `selector.py` — mechanical shadow rule
- `risk_gate.py` (pre-LLM) and `pretrade_gate.py` (post-LLM re-check) — the two gates
- `executor_mcp.py` — order execution via Alpaca MCP; `reconciler.py` — broker↔DB truth
- `shadow_book.py` — virtual books: 'shadow' (rule), 'random' (matched), 'menu' (every candidate, regret)
- `backtest_lab.py` — offline component-ladder lab; results in `lab_*` tables
- `dashboard/` — Next.js on Vercel; `supabase/` — schema; `tests/` — pytest suite
- `NIGHTLY.md` — nightly engineer diary; `prompts/evening_engineer.md` — its charter

## Commands
- Tests: `python -m pytest tests/ -q` (must stay green; venv: `source .venv/bin/activate`)
- One simulated cycle: `set -a; source .env; set +a; DRY_RUN=true python bot.py`
- Dashboard build check: `cd dashboard && npx next build` (required if you touch `dashboard/`)

## Non-negotiable conventions
- NEVER commit `.env` or credentials; never print secrets.
- Never LOOSEN risk limits (`risk_gate.py`, config caps); tightening needs written justification.
- Alpaca sign gotcha: top-level `filled_avg_price` is *cost to acquire* — NEGATIVE for
  credit spreads. Tests in `tests/test_fill_confirmation_sign.py` encode this; do not "fix" them.
- Postgres numerics arrive as STRINGS in JS — always `Number()` coerce in the dashboard.
- `state/` is gitignored (anchored as `/state/`) — runtime artifacts only, never code.
- If you change behavior, update the tests that describe it in the same session.
