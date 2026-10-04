"""Single-leg option orders via the same Alpaca MCP server. Marketable
limits only (buy at mid + slip cap, sell at mid - slip cap); content-derived
idempotent ids for opens; DRY_RUN honored."""
from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timezone

from premium_buyer import config as pcfg

logger = logging.getLogger(__name__)
SLIP = 0.05  # accept up to 5% through mid


def _cid(action: str, symbol: str, contracts: int) -> str:
    window = datetime.now(timezone.utc).strftime("%Y%m%d%H")
    h = hashlib.sha1(f"prem|{action}|{symbol}|{contracts}|{window}".encode()).hexdigest()[:10]
    return f"prem-{action}-{h}"


async def buy(mcp, symbol: str, contracts: int, mid: float) -> dict | None:
    cid = _cid("open", symbol, contracts)
    limit = round(mid * (1 + SLIP), 2)
    if pcfg.DRY_RUN:
        logger.info("DRY_RUN: would buy %sx %s limit %.2f (%s)", contracts, symbol, limit, cid)
        return {"id": f"dryrun-{cid}", "client_order_id": cid, "status": "dry_run",
                "fill_price": mid}
    result = await mcp.call("place_option_order", {
        "legs": [{"symbol": symbol, "side": "buy", "ratio_qty": "1",
                  "position_intent": "buy_to_open", "client_order_id": cid + "-l"}],
        "qty": str(contracts), "order_class": "simple", "type": "limit",
        "limit_price": str(limit), "time_in_force": "day", "client_order_id": cid,
    })
    payload = result.get("data", result) if isinstance(result, dict) else result
    if isinstance(payload, dict) and "error" in payload:
        logger.error("premium buy rejected: %s", payload["error"])
        return None
    oid = payload.get("id") if isinstance(payload, dict) else None
    px = payload.get("filled_avg_price") if isinstance(payload, dict) else None
    return {"id": oid, "client_order_id": cid,
            "status": str(payload.get("status", "accepted")).lower() if isinstance(payload, dict) else "accepted",
            "fill_price": abs(float(px)) if px is not None else None}


async def sell_to_close(mcp, symbol: str, contracts: int, mid: float) -> dict | None:
    cid = _cid(f"close-{datetime.now(timezone.utc).strftime('%M%S')}", symbol, contracts)
    limit = max(round(mid * (1 - SLIP), 2), 0.01)
    if pcfg.DRY_RUN:
        logger.info("DRY_RUN: would sell %sx %s limit %.2f", contracts, symbol, limit)
        return {"id": f"dryrun-{cid}", "status": "dry_run", "fill_price": mid}
    result = await mcp.call("place_option_order", {
        "legs": [{"symbol": symbol, "side": "sell", "ratio_qty": "1",
                  "position_intent": "sell_to_close", "client_order_id": cid + "-l"}],
        "qty": str(contracts), "order_class": "simple", "type": "limit",
        "limit_price": str(limit), "time_in_force": "day", "client_order_id": cid,
    })
    payload = result.get("data", result) if isinstance(result, dict) else result
    if isinstance(payload, dict) and "error" in payload:
        logger.error("premium close rejected: %s", payload["error"])
        return None
    px = payload.get("filled_avg_price") if isinstance(payload, dict) else None
    return {"id": payload.get("id") if isinstance(payload, dict) else None,
            "status": str(payload.get("status", "accepted")).lower() if isinstance(payload, dict) else "accepted",
            "fill_price": abs(float(px)) if px is not None else None}
