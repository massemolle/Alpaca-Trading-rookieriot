#!/usr/bin/env bash
set -uo pipefail
cd "$(dirname "$0")"
export PATH="$HOME/.local/bin:$PATH"
mkdir -p state
exec 200>state/council.lock
flock -w 120 200 || exit 0
source .venv/bin/activate
set -a; source .env; set +a
timeout 400 python -m arm_council.run
