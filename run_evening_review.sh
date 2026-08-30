#!/usr/bin/env bash
# Nightly engineer (Fable) with a hard verification gate.
# Fable may edit the trading algorithm freely within its charter
# (prompts/evening_engineer.md); the gate below decides whether the changes
# survive: compile + full test suite + one forced-DRY_RUN cycle, else full
# revert. Scheduled 21:00 UTC Mon-Fri (after the close and after the last
# trading cron tick).
set -uo pipefail
cd "$(dirname "$0")"
mkdir -p state

# Never overlap a trading cycle (waits up to 10 min, then gives up).
exec 200>state/bot.lock
if ! flock -w 600 200; then
    echo "bot.lock still held — skipping tonight's review"
    exit 0
fi

source .venv/bin/activate
set -a; source .env; set +a

python evening_context.py || echo "WARNING: context build failed — Fable reviews without DB context"

cp .env state/.env.backup
crontab -l > state/crontab.backup 2>/dev/null || true
GIT_BEFORE=$(git rev-parse HEAD)

echo "=== nightly engineer session (claude-fable-5) $(date -u) ==="
# Credentials are scrubbed from the child env — the engineer edits code, it
# never needs broker/DB/bot secrets.
env -u ALPACA_SECRET_KEY -u ALPACA_API_KEY -u SUPABASE_DB_PASSWORD -u TELEGRAM_BOT_TOKEN \
    claude -p "$(cat prompts/evening_engineer.md)" \
    --model claude-fable-5 \
    --permission-mode acceptEdits \
    --output-format text \
    > state/evening_review_last.md 2> state/evening_review_err.log
echo "--- engineer stdout saved to state/evening_review_last.md"

# Protected files restored no matter what the session did.
cp state/.env.backup .env
crontab state/crontab.backup 2>/dev/null || true

# ---- THE GATE ---------------------------------------------------------------
GATE_LOG=state/evening_gate.log
: > "$GATE_LOG"
gate_ok=true
python -m py_compile bot.py pretrade_gate.py executor_mcp.py llm_reasoner.py \
    risk_gate.py spread_builder.py shadow_book.py db.py selector.py \
    reconciler.py benchmark.py backtest_lab.py >> "$GATE_LOG" 2>&1 || gate_ok=false
$gate_ok && python -m pytest tests/ -q >> "$GATE_LOG" 2>&1 || gate_ok=false
$gate_ok && DRY_RUN=true timeout 280 python bot.py >> "$GATE_LOG" 2>&1 || gate_ok=false
# Dashboard build gate — only when the session touched dashboard/ (learned
# 2026-08-30: a type mismatch reached Vercel because nothing built the
# dashboard pre-push; production silently served a stale build for a day).
if $gate_ok && ! git diff --quiet "$GIT_BEFORE" -- dashboard/; then
    (cd dashboard && npx next build) >> "$GATE_LOG" 2>&1 || gate_ok=false
fi

if $gate_ok; then
    if git diff --quiet && git diff --cached --quiet && [ -z "$(git status --porcelain=v1 2>/dev/null | grep -v '^?? state/')" ]; then
        echo "GATE PASSED — engineer made no code changes tonight"
    else
        git add -A -- . ':!state'
        git commit -m "Nightly engineer (Fable) $(date -u +%F): gate passed (compile + tests + dry cycle)

Review: state/evening_review_last.md · Charter: prompts/evening_engineer.md
Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>" || true
        git pull --rebase --autostash origin main >> "$GATE_LOG" 2>&1 || echo "WARNING: rebase failed — resolve manually"
        git push origin main >> "$GATE_LOG" 2>&1 || echo "WARNING: push failed — commit kept locally"
        echo "GATE PASSED — changes committed: $(git log --oneline -1)"
    fi
else
    echo "GATE FAILED — reverting the engineer's changes (see $GATE_LOG)"
    git reset --hard "$GIT_BEFORE"
    git clean -fd -e state -e .env -e .venv -e dashboard/node_modules -e dashboard/.next >> "$GATE_LOG" 2>&1
fi
tail -3 "$GATE_LOG" || true
