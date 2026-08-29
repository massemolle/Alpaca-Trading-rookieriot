# Monday runbook — symptom → one command

Everything here is reversible and takes under a minute. When in doubt: STOP
the bot first (step 1), diagnose second. The market will still be there.

## 1. STOP new trading (any severity)
```
crontab -l | grep -v run_options_cron | crontab -
```
Re-enable later:
```
(crontab -l; echo "*/30 13-20 * * 1-5 /home/ubuntu/Alpaca-Trading-rookieriot/run_options_cron.sh >> /home/ubuntu/Alpaca-Trading-rookieriot/state/cron.log 2>&1") | crontab -
```

## 2. Back to simulation (bot keeps running, orders stop)
Edit `.env`: `DRY_RUN=true`  (next cycle logs orders instead of placing them)

## 3. Close everything now (positions look wrong / runaway)
```
set -a; source .env; set +a; python emergency_flatten.py
```
Honors DRY_RUN. Asks for confirmation ("flatten"). If MCP itself is broken,
close manually: app.alpaca.markets → paper account → Positions → liquidate.

## 4. Roll back a bad code change
```
git log --oneline -10          # find the last good commit
git revert <bad_commit>        # or: git reset --hard <good> && git push -f
```
The gate/journal/tests landed in small commits — revert is surgical.

## 5. Diagnose before changing anything
- `tail -50 state/bot.log` — every INFO line of the last cycles
- `tail -30 state/cron.log` — did cron even fire? lock contention?
- Dashboard "Recent agent decisions" — what did it decide and why
- `python -m pytest tests/ -q` — 23 tests; a red one names the broken part
- One manual cycle with full visibility:
  `set -a; source .env; set +a; python bot.py` (DRY_RUN=true first!)

## 6. Reasoner misbehaving (bad picks, timeouts)
- Abstain-on-failure is built in: worst case = no trades, never bad parses
- Disable LLM entirely (mechanical shadow rule continues to journal):
  `.env`: `REASONER_MODE=openai` with no key → decide() fails safe → abstains
- Claude quota exhausted (subscription limits): same abstention path; check
  `claude -p "ok"` manually

## 7. Who to call
Alex — his stack is independent; worst case he re-points his instance at the
judged account (ONLY after our cron is disabled — one live trader per account).

## Known-safe baseline
Commit tagged in git history: every commit on main passed 23 tests + a dry
cycle before push. `git log --oneline` = the audit trail.
