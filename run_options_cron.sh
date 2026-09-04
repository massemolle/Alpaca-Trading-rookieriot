#!/usr/bin/env bash
# Cron entry point — same lock/silent-delivery shape as
# trading_bot/run_paper_cron.sh, simplified because bot.py already decides
# for itself what's worth printing (only opens/closes/errors reach stdout).
# Failures now exit non-zero so monitoring can alert.
set -uo pipefail
cd "$(dirname "$0")"
# Cron's bare PATH doesn't include ~/.local/bin, where the `claude` binary
# lives — without this, llm_reasoner's subprocess fails and every LLM
# decision silently degrades to abstention (found 2026-09-01: the nightly
# engineer never ran night one for the same reason).
export PATH="$HOME/.local/bin:$PATH"
mkdir -p state
exec 200>state/bot.lock
# A cycle can take a while (MCP subprocess spin-up + several option-chain
# calls + an LLM round-trip); the lock stops two invocations from ever
# racing to open/close the same spread if one run overruns the schedule.
if ! flock -n 200; then
    echo "bot.py already running (lock held), skipping this invocation"
    exit 0
fi
source .venv/bin/activate
set -a
source .env
set +a

OUTPUT=$(python bot.py 2>&1) || {
    status=$?
    echo "⚠️ OPTIONS AGENT ERROR (exit $status):"
    echo "$OUTPUT" | tail -40
    exit "$status"
}

if [ -n "$OUTPUT" ]; then
    echo "$OUTPUT"
fi
