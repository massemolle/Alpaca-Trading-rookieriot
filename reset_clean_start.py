"""Full clean start (approved 2026-08-30): wipe our schema's TRADING history
and record a fresh baseline snapshot — clean equity curve and vs-SPY
baseline for judging. Lab/backtest tables are kept (simulation history).

Run AFTER the account/keys question is settled, with the final keys in .env:
    set -a; source .env; set +a; python reset_clean_start.py --yes

Prints the account identity first so you can confirm you're baselining the
right account. Without --yes it only shows what it would delete.
"""
from __future__ import annotations

import sys

import benchmark
import db
from alpaca_client import AlpacaClient


TABLES = ["shadow_positions", "decision_journal", "spreads", "cycles", "account_snapshots"]


def main() -> None:
    client = AlpacaClient()
    account = client.get_account()
    import requests  # account number isn't in AlpacaClient.get_account(); fetch raw
    import os
    r = requests.get(
        f"{os.environ.get('ALPACA_BASE_URL', 'https://paper-api.alpaca.markets')}/v2/account",
        headers={"APCA-API-KEY-ID": os.environ["ALPACA_API_KEY"],
                 "APCA-API-SECRET-KEY": os.environ["ALPACA_SECRET_KEY"]},
        timeout=15,
    ).json()
    print(f"Account: {r.get('account_number')}  equity: {account['equity']}")

    counts = {}
    import psycopg2.extras
    with db._connection() as conn, conn.cursor() as cur:
        for t in TABLES:
            cur.execute(f"select count(*) from {db._schema()}.{t}")
            counts[t] = cur.fetchone()[0]
    print("Would delete:", counts, "(lab_trades / lab_summary kept)")

    if "--yes" not in sys.argv:
        print("Dry preview only — rerun with --yes to execute.")
        return

    with db._connection() as conn, conn.cursor() as cur:
        for t in TABLES:
            cur.execute(f"delete from {db._schema()}.{t}")
    print("History wiped.")

    equity = float(account["equity"])
    last_equity = float(account["last_equity"])
    db.record_account_snapshot(
        equity=equity, last_equity=last_equity,
        cash=float(account["cash"]) if account.get("cash") is not None else None,
        open_spreads_count=0,
        daily_pl=equity - last_equity,
        daily_pl_pct=(equity - last_equity) / last_equity if last_equity else 0.0,
        spy_price=benchmark.spy_mid(client),
    )
    print(f"Fresh baseline recorded: equity={equity:,.2f}. Dashboard starts clean.")


if __name__ == "__main__":
    main()
