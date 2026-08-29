"""SPY benchmark helper — one price per snapshot so the dashboard can show
'skill vs market' (synthetic buy-and-hold SPY overlay; PLAN Science section).
Never blocks a snapshot: any failure returns None.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def spy_mid(client) -> float | None:
    try:
        q = client.get_latest_quote("SPY")
        return round((float(q["ask_price"]) + float(q["bid_price"])) / 2, 2)
    except Exception:
        logger.exception("SPY benchmark quote failed (snapshot proceeds without it)")
        return None
