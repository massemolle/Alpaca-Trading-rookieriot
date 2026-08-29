"""Offline tests for shadow_book's counterfactual selection semantics."""
from __future__ import annotations

import shadow_book
from tests.conftest import make_plan


def _candidates(tickers):
    return [
        {"ticker": t, "direction": "bull_put", "strength": 0.5,
         "credit_estimate": 100.0, "max_loss": 400.0, "_plan": make_plan(underlying=t)}
        for t in tickers
    ]


def _sizing(equity, max_loss_per_contract, max_risk_pct):
    return 2


def run_open(monkeypatch, *, llm, shadow, cands, cycle_id=42):
    recorded = []
    monkeypatch.setattr(
        shadow_book, "_record_open",
        lambda cycle_id, policy, cand, plan, contracts, same_as_llm: recorded.append(
            {"policy": policy, "ticker": plan.underlying, "contracts": contracts, "same_as_llm": same_as_llm}
        ),
    )
    shadow_book.open_counterfactuals(
        cycle_id=cycle_id, candidates=cands, llm_selected=llm, shadow_selected=shadow,
        sizing_fn=_sizing, equity=100_000.0, max_risk_pct=0.02,
    )
    return recorded


def test_matched_trade_rate(monkeypatch):
    cands = _candidates(["AAA", "BBB", "CCC"])
    rec = run_open(monkeypatch, llm=["AAA", "BBB"], shadow=["CCC"], cands=cands)
    randoms = [r for r in rec if r["policy"] == "random"]
    shadows = [r for r in rec if r["policy"] == "shadow"]
    assert len(randoms) == 2  # same count as the LLM took
    assert len(shadows) == 1 and shadows[0]["ticker"] == "CCC"
    assert all(r["contracts"] == 2 for r in rec)  # same sizing rule


def test_random_abstains_when_llm_abstains(monkeypatch):
    cands = _candidates(["AAA", "BBB"])
    rec = run_open(monkeypatch, llm=[], shadow=["AAA"], cands=cands)
    assert [r["policy"] for r in rec] == ["shadow"]  # no random rows


def test_random_is_deterministic_per_cycle(monkeypatch):
    cands = _candidates(["AAA", "BBB", "CCC", "DDD"])
    r1 = run_open(monkeypatch, llm=["AAA"], shadow=[], cands=cands, cycle_id=7)
    r2 = run_open(monkeypatch, llm=["AAA"], shadow=[], cands=cands, cycle_id=7)
    assert [x["ticker"] for x in r1] == [x["ticker"] for x in r2]


def test_same_as_llm_flag(monkeypatch):
    cands = _candidates(["AAA"])
    rec = run_open(monkeypatch, llm=["AAA"], shadow=["AAA"], cands=cands)
    shadows = [r for r in rec if r["policy"] == "shadow"]
    assert shadows[0]["same_as_llm"] is True


def test_never_raises(monkeypatch):
    monkeypatch.setattr(shadow_book, "_record_open", lambda *a, **k: 1 / 0)
    shadow_book.open_counterfactuals(
        cycle_id=1, candidates=_candidates(["AAA"]), llm_selected=["AAA"],
        shadow_selected=["AAA"], sizing_fn=_sizing, equity=1.0, max_risk_pct=0.02,
    )  # swallowed, logged
