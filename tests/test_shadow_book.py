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


def test_citation_check_warns_on_unknown_ids(caplog):
    import logging
    import llm_reasoner

    cands = [{"ticker": "SPY", "facts": [{"fact_id": "SPY_CREDIT_EST"}]}]
    with caplog.at_level(logging.WARNING):
        llm_reasoner._check_citations(cands, "credit [SPY_CREDIT_EST] and made-up [SPY_IV_RANK]")
    assert "SPY_IV_RANK" in caplog.text
    caplog.clear()
    with caplog.at_level(logging.WARNING):
        llm_reasoner._check_citations(cands, "only real [SPY_CREDIT_EST]")
    assert caplog.text == ""


# ---- menu book (full counterfactual menu + regret) --------------------------

def _menu_candidates(tickers):
    return [
        {"ticker": t, "direction": "bull_put", "strength": 0.5,
         "credit_estimate": 100.0, "max_loss": 400.0,
         "_plan": make_plan(underlying=t, short_symbol=f"{t}_S", long_symbol=f"{t}_L")}
        for t in tickers
    ]


def run_menu(monkeypatch, *, llm, cands, already=frozenset(), cap="20"):
    recorded = []
    monkeypatch.setenv("MENU_BOOK_MAX_OPEN", cap)
    monkeypatch.setattr(shadow_book, "_menu_open_symbol_pairs", lambda: set(already))
    monkeypatch.setattr(
        shadow_book, "_record_open",
        lambda cycle_id, policy, cand, plan, contracts, same_as_llm: recorded.append(
            {"policy": policy, "ticker": plan.underlying, "contracts": contracts, "same_as_llm": same_as_llm}
        ),
    )
    shadow_book.open_menu_book(
        cycle_id=7, candidates=cands, llm_selected=llm,
        sizing_fn=_sizing, equity=100_000.0, max_risk_pct=0.02,
    )
    return recorded


def test_menu_records_every_candidate(monkeypatch):
    rec = run_menu(monkeypatch, llm=["AAA"], cands=_menu_candidates(["AAA", "BBB", "CCC"]))
    assert [r["policy"] for r in rec] == ["menu"] * 3
    assert {r["ticker"]: r["same_as_llm"] for r in rec} == {"AAA": True, "BBB": False, "CCC": False}


def test_menu_dedups_open_symbol_pairs(monkeypatch):
    rec = run_menu(monkeypatch, llm=[], cands=_menu_candidates(["AAA", "BBB"]),
                   already={("AAA_S", "AAA_L")})
    assert [r["ticker"] for r in rec] == ["BBB"]


def test_menu_cap_limits_new_opens(monkeypatch):
    rec = run_menu(monkeypatch, llm=[], cands=_menu_candidates(["AAA", "BBB", "CCC"]), cap="2")
    assert len(rec) == 2


def test_menu_never_raises(monkeypatch):
    monkeypatch.setattr(shadow_book, "_menu_open_symbol_pairs", lambda: 1 / 0)
    shadow_book.open_menu_book(
        cycle_id=1, candidates=_menu_candidates(["AAA"]), llm_selected=[],
        sizing_fn=_sizing, equity=1.0, max_risk_pct=0.02,
    )  # swallowed, logged


def test_regret_summary_math():
    rows = [
        # closed winner the LLM dropped -> regret
        {"cycle_id": 1, "underlying": "AAA", "direction": "bull_put", "short_strike": 10,
         "long_strike": 5, "expiration": "2026-09-11", "status": "closed_profit",
         "same_as_llm": False, "credit_received": 100.0, "contracts": 2, "realized_pnl": 120.0},
        # open marked loser the LLM took: (100 - 130) * 1
        {"cycle_id": 2, "underlying": "BBB", "direction": "bear_call", "short_strike": 20,
         "long_strike": 25, "expiration": "2026-09-11", "status": "open",
         "same_as_llm": True, "credit_received": 100.0, "contracts": 1,
         "realized_pnl": None, "unrealized_mark": 130.0},
        # never marked -> excluded from totals
        {"cycle_id": 3, "underlying": "CCC", "direction": "bull_put", "short_strike": 30,
         "long_strike": 25, "expiration": "2026-09-11", "status": "open",
         "same_as_llm": False, "credit_received": 100.0, "contracts": 1,
         "realized_pnl": None, "unrealized_mark": None},
    ]
    s = shadow_book.regret_summary(rows)
    assert s["dropped_count"] == 1 and s["dropped_positive_total_usd"] == 120.0
    assert s["taken_count"] == 1 and s["taken_total_usd"] == -30.0
    assert s["best_dropped"]["underlying"] == "AAA"
    assert len(s["rows"]) == 3 and s["rows"][2]["outcome_usd"] is None
