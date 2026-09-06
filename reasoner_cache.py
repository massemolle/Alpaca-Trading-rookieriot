"""Content-hash cache for the LLM selector (Roadmap v2, ai-hedge-fund pattern).

If the decision-relevant content of the candidate menu is unchanged since a
previous cycle TODAY, reuse that decision instead of paying for a new LLM
call — cheaper, faster, and more consistent (the same facts should not get
two different answers an hour apart).

"Unchanged" is deliberately tolerant of quote noise: credits and losses are
bucketed to $5, signal strength to 0.01, spot excluded entirely (strikes and
expiration already pin the trade's geometry). Timestamps (`as_of`) are
excluded — that is the whole point. Book-context facts (OPEN_SPREADS /
OPEN_MAX_LOSS) ARE included, so any change in what we hold invalidates the
cache. Scope: same UTC trading day only. Disable with REASONER_CACHE=false.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

_CACHE_PATH = Path(__file__).resolve().parent / "state" / "reasoner_cache.json"


def enabled() -> bool:
    return os.environ.get("REASONER_CACHE", "true").lower() == "true"


def _bucket(value, step: float):
    try:
        return round(float(value) / step) * step
    except (TypeError, ValueError):
        return value


def menu_hash(candidates: list[dict], remaining_budget: int) -> str:
    day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    normalized = []
    for c in sorted(candidates, key=lambda x: x.get("ticker", "")):
        entry = {
            "ticker": c.get("ticker"),
            "direction": c.get("direction"),
            "strength": _bucket(c.get("strength"), 0.01),
            "credit": _bucket(c.get("credit_estimate"), 5.0),
            "max_loss": _bucket(c.get("max_loss"), 5.0),
            "contracts": c.get("contracts"),
            "expiration": str(c.get("expiration")),
        }
        for f in c.get("facts", []) or []:
            fid = f.get("fact_id", "")
            if fid.endswith("_OPEN_SPREADS") or fid.endswith("_OPEN_MAX_LOSS"):
                entry[fid] = f.get("value")
        normalized.append(entry)
    payload = json.dumps({"day": day, "budget": remaining_budget, "menu": normalized},
                         sort_keys=True, default=str)
    return hashlib.sha256(payload.encode()).hexdigest()[:24]


def get(key: str) -> dict | None:
    try:
        if not _CACHE_PATH.exists():
            return None
        data = json.loads(_CACHE_PATH.read_text())
        hit = data.get(key)
        if not hit:
            return None
        # Same-day scope is baked into the key via `day`; nothing to expire.
        return hit
    except Exception:
        logger.exception("reasoner cache read failed (treated as miss)")
        return None


def put(key: str, outcome: dict, cycle_hint: str) -> None:
    try:
        data = {}
        if _CACHE_PATH.exists():
            data = json.loads(_CACHE_PATH.read_text())
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        # Drop stale days so the file never grows unbounded.
        data = {k: v for k, v in data.items() if v.get("day") == today}
        data[key] = {"selected": outcome.get("selected", []),
                     "reasoning": outcome.get("reasoning", ""),
                     "day": today, "from": cycle_hint}
        _CACHE_PATH.parent.mkdir(exist_ok=True)
        _CACHE_PATH.write_text(json.dumps(data, indent=1))
    except Exception:
        logger.exception("reasoner cache write failed (non-fatal)")
