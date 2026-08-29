"""EMERGENCY: close every open spread now, at marketable limit, and record.

Shares state/bot.lock with the cron so it cannot race bot.py / spread_monitor.
Reconciles against Alpaca first; if the local book is empty but broker has
option legs, lists them and refuses to invent closes without DB rows.

Usage:  set -a; source .env; set +a; python emergency_flatten.py [--yes]
"""
from __future__ import annotations

import asyncio
import fcntl
import sys
from pathlib import Path

import db
import executor_mcp
import reconciler
from alpaca_client import AlpacaClient
from config import config
from mcp_client import AlpacaMCP

LOCK_PATH = Path(__file__).resolve().parent / "state" / "bot.lock"


def _acquire_lock():
    LOCK_PATH.parent.mkdir(exist_ok=True)
    fh = open(LOCK_PATH, "a")
    try:
        fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        fh.close()
        print("ERROR: bot.lock held by another process — aborting flatten")
        sys.exit(2)
    return fh


async def main() -> None:
    lock_fh = _acquire_lock()
    try:
        client = AlpacaClient()
        recon = reconciler.reconcile(client, block_on_mismatch=False)
        if recon.reasons:
            print(f"Reconcile warnings: {recon.reason}")

        spreads = db.get_open_spreads() + db.get_spreads_by_status("pending")
        if not spreads:
            if recon.broker_option_symbols:
                print(
                    "No open spreads in DB, but broker has option legs: "
                    f"{sorted(recon.broker_option_symbols)} — close manually in Alpaca UI"
                )
            else:
                print("No open spreads in the book — nothing to flatten.")
            return

        mode = "DRY_RUN (simulated)" if config.dry_run else "LIVE"
        print(f"[{mode}] {len(spreads)} open/pending spread(s):")
        for s in spreads:
            print(
                f"  #{s['id']} {s['underlying']} {s['direction']} "
                f"x{s.get('contracts', 1)} status={s.get('status')} "
                f"short={s['short_symbol']} long={s['long_symbol']}"
            )
        if "--yes" not in sys.argv:
            answer = input("Close ALL of these now? type 'flatten' to confirm: ").strip()
            if answer != "flatten":
                print("aborted")
                return

        async with AlpacaMCP() as mcp:
            for s in spreads:
                try:
                    contracts = int(s.get("contracts") or 1)
                    mark = await executor_mcp.get_spread_mark(
                        mcp, s["short_symbol"], s["long_symbol"]
                    )
                    limit_debit = (
                        executor_mcp.limit_debit_price(mark)
                        if mark is not None
                        else executor_mcp.limit_debit_price(
                            float(s.get("credit_received") or 100) * 2
                        )
                    )
                    order = await executor_mcp.close_spread(
                        mcp, s["short_symbol"], s["long_symbol"], contracts,
                        client=client,
                        limit_debit=limit_debit,
                        underlying=s["underlying"],
                        direction=s.get("direction") or "close",
                    )
                    db.record_spread_close(s["id"], "closed_emergency", None)
                    print(f"  closed #{s['id']} → orders {order.order_ids} status={order.status}")
                except Exception as exc:
                    print(f"  FAILED to close #{s['id']}: {exc} — close manually in the Alpaca UI")
        print("Done. Verify positions in the Alpaca dashboard (paper account).")
    finally:
        fcntl.flock(lock_fh, fcntl.LOCK_UN)
        lock_fh.close()


if __name__ == "__main__":
    asyncio.run(main())
