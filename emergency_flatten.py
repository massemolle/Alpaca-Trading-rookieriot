"""EMERGENCY: close every open spread now, at market, and record the closes.

The break-glass tool for Monday problems (see docs/runbooks/monday.md).
Honors DRY_RUN — with DRY_RUN=true it shows what it WOULD close; set
DRY_RUN=false in the environment to close for real.

Usage:  set -a; source .env; set +a; python emergency_flatten.py [--yes]
"""
from __future__ import annotations

import asyncio
import sys

import db
import executor_mcp
from config import config
from mcp_client import AlpacaMCP


async def main() -> None:
    spreads = db.get_open_spreads()
    if not spreads:
        print("No open spreads in the book — nothing to flatten.")
        return
    mode = "DRY_RUN (simulated)" if config.dry_run else "LIVE"
    print(f"[{mode}] {len(spreads)} open spread(s):")
    for s in spreads:
        print(f"  #{s['id']} {s['underlying']} {s['direction']} x{s.get('contracts', 1)} "
              f"short={s['short_symbol']} long={s['long_symbol']}")
    if "--yes" not in sys.argv:
        answer = input("Close ALL of these now? type 'flatten' to confirm: ").strip()
        if answer != "flatten":
            print("aborted")
            return
    async with AlpacaMCP() as mcp:
        for s in spreads:
            try:
                contracts = int(s.get("contracts") or 1)
                order_ids = await executor_mcp.close_spread(
                    mcp, s["short_symbol"], s["long_symbol"], contracts
                )
                # P&L unknown at market-order time; recorded as None and the
                # reconciliation is the fill on Alpaca — better honest-unknown
                # than a made-up number (same convention as bot.py's
                # mark-unavailable close path).
                db.record_spread_close(s["id"], "closed_emergency", None)
                print(f"  closed #{s['id']} → orders {order_ids}")
            except Exception as exc:
                print(f"  FAILED to close #{s['id']}: {exc} — close manually in the Alpaca UI")
    print("Done. Verify positions in the Alpaca dashboard (paper account).")


if __name__ == "__main__":
    asyncio.run(main())
