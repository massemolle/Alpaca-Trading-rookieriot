"""SPY benchmark helper — one price per snapshot so the dashboard can show
'skill vs market' (synthetic buy-and-hold SPY overlay; PLAN Science section).
Never blocks a snapshot: any failure returns None.
"""
from __future__ import annotations

import logging

from alpaca_client import two_sided_mid

logger = logging.getLogger(__name__)


def spy_mid(client) -> float | None:
    try:
        q = client.get_latest_quote("SPY")
        mid = two_sided_mid(q)
        if mid is None:
            # One-sided book (routine just after the 4pm close): no benchmark
            # point beats recording half the real price (2026-09-30: 381.19
            # stored against a 762.34 close).
            logger.warning(
                "SPY quote one-sided (bid=%s ask=%s) — snapshot proceeds "
                "without a benchmark point",
                q.get("bid_price"), q.get("ask_price"),
            )
            return None
        return round(mid, 2)
    except Exception:
        logger.exception("SPY benchmark quote failed (snapshot proceeds without it)")
        return None
