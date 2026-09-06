"""Content-hash selector cache (Roadmap v2) — offline."""
from __future__ import annotations

import reasoner_cache


def _cand(ticker="QQQ", strength=0.41, credit=76.0, open_spreads=0):
    return {"ticker": ticker, "direction": "short", "strength": strength,
            "credit_estimate": credit, "max_loss": 500 - credit, "contracts": 1,
            "expiration": "2026-09-14",
            "facts": [{"fact_id": f"{ticker}_OPEN_SPREADS", "value": open_spreads}]}


def test_hash_stable_under_quote_noise():
    a = reasoner_cache.menu_hash([_cand(credit=76.0, strength=0.412)], 3)
    b = reasoner_cache.menu_hash([_cand(credit=77.5, strength=0.408)], 3)  # <$5, <0.01
    assert a == b


def test_hash_changes_on_material_changes():
    base = reasoner_cache.menu_hash([_cand()], 3)
    assert reasoner_cache.menu_hash([_cand(credit=96.0)], 3) != base       # credit moved
    assert reasoner_cache.menu_hash([_cand(open_spreads=2)], 3) != base    # book changed
    assert reasoner_cache.menu_hash([_cand()], 1) != base                  # budget changed
    assert reasoner_cache.menu_hash([_cand(), _cand(ticker="SPY")], 3) != base


def test_put_get_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr(reasoner_cache, "_CACHE_PATH", tmp_path / "cache.json")
    key = reasoner_cache.menu_hash([_cand()], 3)
    assert reasoner_cache.get(key) is None
    reasoner_cache.put(key, {"selected": ["QQQ"], "reasoning": "test"}, "14:00 UTC")
    hit = reasoner_cache.get(key)
    assert hit and hit["selected"] == ["QQQ"] and hit["from"] == "14:00 UTC"


def test_env_toggle(monkeypatch):
    monkeypatch.setenv("REASONER_CACHE", "false")
    assert not reasoner_cache.enabled()
    monkeypatch.setenv("REASONER_CACHE", "true")
    assert reasoner_cache.enabled()
