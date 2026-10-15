"""Arm 4 (Should-AI-Buy replication) — the council is deterministic, so
every decision path is exactly testable offline."""
from __future__ import annotations

import pandas as pd
import pytest

from arm_council import config as ccfg, council, features, scoring


def snap(**kw):
    base = dict(symbol="TEST", price=100.0, change24h=1.0, rsi14=60.0, rvol=1.3,
                volume_accel=10.0, realized_vol=25.0, liquidity_usd=5_000_000.0,
                spread_bps=5.0, momentum=70.0)
    base.update(kw)
    return scoring.Snapshot(**base)


# ---- scoring formulas (transcribed from their TS) ---------------------------

def test_trend_and_volatility_bands():
    assert scoring.trend_score(60) == 80 and scoring.trend_score(72) == 65
    assert scoring.trend_score(35) == 30 and scoring.trend_score(45) == 50
    assert scoring.volatility_score(25) == 90 and scoring.volatility_score(45) == 70
    assert scoring.volatility_score(60) == 40


def test_liquidity_tiers():
    assert scoring.liquidity_score(6e6, 8) == 95
    assert scoring.liquidity_score(2e6, 20) == 80
    assert scoring.liquidity_score(200_000, 40) == 65
    assert scoring.liquidity_score(50_000, 80) == 30


def test_regime_classification():
    assert scoring.classify_regime(snap(realized_vol=60, rsi14=40, momentum=30)) == "RISK_OFF"
    assert scoring.classify_regime(snap(rsi14=60, momentum=70, rvol=1.4, volume_accel=5)) == "RISK_ON"
    assert scoring.classify_regime(snap(rsi14=60, momentum=70, rvol=0.8, volume_accel=-5)) == "TRENDING_UP"
    assert scoring.classify_regime(snap(rsi14=40, momentum=30, realized_vol=25)) == "TRENDING_DOWN"
    assert scoring.classify_regime(snap(rsi14=50, momentum=50, realized_vol=10, rvol=0.5)) == "LOW_VOLATILITY"


# ---- the red team veto (the mechanism that actually decides) ----------------

def test_red_team_two_vulnerabilities_disprove():
    vulns, status = council.red_team(snap(liquidity_usd=100_000, rsi14=80, realized_vol=60))
    assert len(vulns) >= 2 and status == "DISPROVED"


def test_red_team_single_vulnerability_only_weakens():
    vulns, status = council.red_team(snap(liquidity_usd=100_000))
    assert len(vulns) == 1 and status == "WEAKENED"


def test_disproved_thesis_forces_reject_and_gate_failure():
    d = council.decide(snap(liquidity_usd=100_000, rsi14=80, realized_vol=60))
    assert d["conclusion"] == "REJECT" and not d["gate_passed"] and not d["tradeable"]


def test_buy_requires_all_three_conditions():
    # opportunity >= 65, risk <= 45, score >= floor
    d = council.decide(snap(momentum=95, volume_accel=60, rvol=2.5, liquidity_usd=9e6))
    assert d["conclusion"] == "BUY" and d["tradeable"]
    # same but illiquid -> risk rises, gate blocks
    d2 = council.decide(snap(momentum=95, volume_accel=60, rvol=2.5, liquidity_usd=200_000))
    assert not d2["tradeable"]


# ---- claim graph -------------------------------------------------------------

def test_refutation_marks_target_refuted():
    d = council.decide(snap(liquidity_usd=100_000, rsi14=80, realized_vol=60))
    by_id = {c["id"]: c for c in d["claims"]}
    quant = next(c for c in d["claims"] if c["agent"] == "quant")
    assert quant["status"] == "REFUTED" and quant["refuted_by_claim_id"]
    # faithful quirk: only the FIRST vulnerability targets anything
    refs = [c for c in d["claims"] if c["type"] == "REFUTATION"]
    assert refs[0]["refutation_of"] is not None
    assert all(r["refutation_of"] is None for r in refs[1:])


def test_derive_status_precedence():
    c = council.Claim("X", "quant", "QUANT", "BULLISH", "s", 50.0,
                      contradictory_evidence_ids=["E1"], supporting_evidence_ids=["E2"])
    assert council.derive_status(c) == "CONTESTED"
    c2 = council.Claim("Y", "quant", "QUANT", "BULLISH", "s", 50.0)
    assert council.derive_status(c2) == "UNSUPPORTED"


# ---- sizing ------------------------------------------------------------------

def test_sizing_respects_caps_and_never_rounds_up():
    size, qty, viol = council.size_position(equity=100_000, cash=50_000, gross_exposure=0,
                                            price=100.0, confidence=86, opportunity=70,
                                            realized_vol=25)
    assert not viol
    assert size <= ccfg.MAX_POSITION_SIZE_USD
    assert qty == int(size // 100.0)          # floored, never rounded up


def test_sizing_blocks_when_exposure_cap_reached():
    _s, _q, viol = council.size_position(100_000, 50_000, 50_000, 100.0, 86, 70, 25)
    assert any("exposure" in v for v in viol)


# ---- exits (with the longer-term twist) --------------------------------------

def test_exit_ladder_uses_longer_term_thresholds():
    assert council.exit_decision(-8.5, 60, 55, 5e6, 20) == "price_drawdown"
    assert council.exit_decision(-6.0, 60, 55, 5e6, 20) is None       # theirs would exit at -5
    assert council.exit_decision(12.0, 45, 55, 5e6, 20) == "profit_target_hit"
    assert council.exit_decision(12.0, 80, 55, 5e6, 20) is None       # no exhaustion -> hold
    assert council.exit_decision(2.0, 25, 55, 5e6, 20) == "momentum_reversal"
    assert council.exit_decision(2.0, 60, 55, 100_000, 20) == "liquidity_deterioration"


# ---- feature builder ---------------------------------------------------------

def test_snapshot_from_bars_shapes():
    n = 60
    bars = pd.DataFrame({
        "close": [100 + i * 0.1 for i in range(n)],
        "high": [101 + i * 0.1 for i in range(n)],
        "low": [99 + i * 0.1 for i in range(n)],
        "volume": [1_000_000] * n,
    })
    s = features.snapshot_from_bars("TEST", bars, bid=105.9, ask=106.1)
    assert s is not None and 0 <= s.rsi14 <= 100 and s.price == pytest.approx(106.0)
    assert s.liquidity_usd > 0 and s.spread_bps < 50


def test_snapshot_rejects_short_history():
    assert features.snapshot_from_bars("T", pd.DataFrame({"close": [1, 2]}), 1, 2) is None


# ---- the optional LLM stage: a ratchet, never an elevator --------------------

def test_llm_review_cannot_create_a_buy(monkeypatch):
    """Their key property: a model reply of BUY can never elevate; only
    HOLD/PASS are honored, and any failure keeps the deterministic action."""
    import json as _json
    import subprocess
    from arm_council import llm_review

    d = {"confidence": 86.0, "regime": "RISK_ON", "multi_factor": 72.0,
         "rr": 2.4, "opportunity": 70.0, "risk": 20.0, "vulnerabilities": []}
    s = snap()

    class R:
        returncode = 0
        stderr = ""
        stdout = _json.dumps({"decision": "BUY", "confidence": 99, "thesis": "moon",
                              "invalidation": "x", "risks": [], "reasoningSummary": "y"})

    monkeypatch.setattr(subprocess, "run", lambda *a, **k: R())
    out = llm_review.review(d, s)
    assert out["action"] == "BUY" and out["downgraded"] is False
    assert out["confidence"] == round((86.0 + 99) / 2)   # blended, not elevated

    class Veto(R):
        stdout = _json.dumps({"decision": "PASS", "confidence": 20, "thesis": "",
                              "invalidation": "", "risks": [], "reasoningSummary": ""})

    monkeypatch.setattr(subprocess, "run", lambda *a, **k: Veto())
    assert llm_review.review(d, s)["action"] == "PASS"

    def boom(*a, **k):
        raise RuntimeError("model down")

    monkeypatch.setattr(subprocess, "run", boom)
    assert llm_review.review(d, s)["action"] == "BUY"     # failure keeps deterministic
