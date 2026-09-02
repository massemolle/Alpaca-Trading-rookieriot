# Monday go-live runbook

Everything here is reversible. When in doubt: **STOP** the bot first (step 1),
diagnose second. The market will still be there.

## Pre-open checklist (before 13:30 UTC / 15:30 CEST)

> **Verified Sunday Aug 30:** keys in `.env` open **PA34CFYP0MIZ** (our account, not
> Alex's) — wrong-account guard passes, equity $100,000 flat, options level 3.
> Clean start executed (`reset_clean_start.py --yes`): history wiped, fresh
> baseline snapshot recorded, dry cycle green, dashboard clean.
> **Go-live rule (approved): flip `DRY_RUN=false` after the FIRST clean dry
> cycle (~15:45 Paris), not after a full dry day.**

- [ ] `DRY_RUN=true` in `.env` until the controlled one-contract rehearsal passes
- [ ] Dedicated ~$100k paper account; options approval enabled; keys only for this account
- [ ] Schema applied: `supabase/alpaca_hackathon_schema.sql` (includes `fill_credit`,
      `client_order_id`, `lab_trades` / `lab_summary`)
- [ ] `UNIVERSE_TICKERS=SPY,QQQ,IWM` (or `SPY,QQQ`); `UNIVERSE_MODE=etf`
- [ ] `MAX_CONTRACTS_PER_SPREAD=1` (do not raise until fill tracking is observed live)
- [ ] Frozen heuristics unchanged: `SHORT_LEG_TARGET_DELTA=0.17`, `MIN_DTE=10`,
      `MAX_DTE=21`, `SPREAD_WIDTH_DOLLARS=5`, `PROFIT_TARGET_PCT=0.50`,
      `STOP_LOSS_MULTIPLE=2.0` — contest defaults, not claimed optima
- [ ] Offline validation green:
  ```
  python -m pytest tests/ -q
  python iv_diagnostic.py          # offline IV round-trip only
  python verify_backtest.py        # mechanics checks (no live API)
  ```
- [ ] Dashboard `/api/state` loads; ablation panel shows LLM / mechanical / random
- [ ] Telegram (or log) alerts reachable; `run_options_cron.sh` exits non-zero on bot failure
- [ ] Shared lock: `emergency_flatten.py` and cron both use `state/bot.lock`

## Controlled go-live (13:30 UTC Monday)

1. One dry cycle on fresh quotes:
   ```
   set -a; source .env; set +a
   DRY_RUN=true python bot.py
   ```
2. Review journal + dashboard: candidates, gates, LLM/shadow/random picks, no reconcile block.
3. Flip `DRY_RUN=false` and submit **one** one-contract SPY or QQQ spread with limit pricing.
4. Wait for confirmed fill (`status=open`, `fill_credit` set). Reconcile broker ↔ DB ↔ dashboard ↔ shadow.
5. Only then enable unattended cron. Keep one contract until quantity-aware gates and fills are observed.

## 1. STOP new trading (any severity)
```
crontab -l | grep -v run_options_cron | crontab -
```
Re-enable later (adjust path):
```
(crontab -l; echo "*/30 13-20 * * 1-5 /path/to/Alpaca-trading/run_options_cron.sh >> /path/to/Alpaca-trading/state/cron.log 2>&1") | crontab -
```

## 2. Back to simulation (bot keeps running, orders stop)
Edit `.env`: `DRY_RUN=true`

## 3. Close everything now
```
set -a; source .env; set +a; python emergency_flatten.py
```
Honors DRY_RUN and the same flock as cron. Asks for confirmation ("flatten").
If MCP is broken: app.alpaca.markets → paper → Positions → liquidate.

## 4. Broker / DB divergence
Any unexplained mismatch **blocks new entries** (`reconcile_block` cycle).
```
set -a; source .env; set +a; python -c "from alpaca_client import AlpacaClient; import reconciler; print(reconciler.reconcile(AlpacaClient()))"
```
Fix phantom/missing rows before re-enabling entries.

## 5. Diagnose
- `tail -50 state/bot.log` / `tail -30 state/cron.log`
- Dashboard “Recent agent decisions” + ablation meta (abstention, gate blocks, slippage)
- `python -m pytest tests/ -q`
- Manual: `DRY_RUN=true python bot.py`

## 6. Reasoner misbehaving
Abstain-on-failure is built in. Empty LLM pick on a non-empty menu → `abstained`.
Disable LLM: remove/break reasoner key → fail-safe abstention; shadow still journals.

## Known-safe framing
This is an **auditable constrained-agent experiment**, not statistically proven LLM
alpha or a universally optimal options strategy. Present sample size, abstention,
gate-block rate, and execution slippage honestly.

## Verification discipline (learned 2026-09-02)
NEVER run a forced-DRY_RUN cycle against the live DB during market hours with
candidates flowing — dry "fills" are recorded into the real spreads/journal
tables (by design, so the nightly gate can verify end-to-end) and desync the
reconciler. The nightly gate's dry cycle is safe (market closed → no
screening). Intraday verification = pytest only.
