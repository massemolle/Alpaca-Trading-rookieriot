"""Record one account snapshot to Supabase — bot.py's per-cycle snapshot step,
standalone. Exists because the vendored screening/ and signals/ packages are
not yet in the repo, so bot.py can't run outside the original machine; this
keeps the dashboard's equity curve fresh in the meantime (and is harmless to
run alongside full cycles — snapshots are append-only).

Usage: set -a; source .env; set +a; python record_snapshot.py
"""
from __future__ import annotations

import benchmark
import db
from alpaca_client import AlpacaClient


def main() -> None:
    client = AlpacaClient()
    account = client.get_account()
    equity = float(account["equity"])
    last_equity = float(account["last_equity"])
    daily_pl = equity - last_equity
    daily_pl_pct = daily_pl / last_equity if last_equity else 0.0
    open_count = len(db.get_open_spreads())
    db.record_account_snapshot(
        equity=equity,
        last_equity=last_equity,
        cash=float(account["cash"]) if account.get("cash") is not None else None,
        open_spreads_count=open_count,
        daily_pl=daily_pl,
        daily_pl_pct=daily_pl_pct,
        spy_price=benchmark.spy_mid(client),
    )
    print(f"snapshot recorded: equity={equity:,.2f} daily_pl={daily_pl:+.2f} open_spreads={open_count}")


if __name__ == "__main__":
    main()
