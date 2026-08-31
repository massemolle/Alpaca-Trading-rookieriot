"""Correlation-cluster concentration gate (2026-08-30, adapted from the
sibling project) — offline, no network."""
from __future__ import annotations

import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import risk_gate
from screening import correlation_clusters


def _base_kwargs(**overrides) -> dict:
    defaults = dict(
        equity=100_000.0,
        daily_pl_pct=0.0,
        open_spreads_count=0,
        max_loss=500.0,
        expiration=date.today() + timedelta(days=14),
        today=date.today(),
    )
    defaults.update(overrides)
    return defaults


def test_cluster_for_known_and_unknown_tickers():
    assert correlation_clusters.cluster_for("NVDA") == "mega_cap_tech"
    assert correlation_clusters.cluster_for("JPM") == "big_banks"
    assert correlation_clusters.cluster_for("XOM") == "energy_majors"
    assert correlation_clusters.cluster_for("SPY") is None  # not in any cluster -- gate simply doesn't apply


def test_cluster_cap_blocks_when_projected_exposure_exceeds_it():
    # 40% of $100k = $40k cap. Already $39,600 in mega_cap_tech (from some
    # other ticker in the same cluster), adding a $500 AAPL spread pushes
    # it to $40,100 -- over the cap.
    check = risk_gate.check_new_spread(
        **_base_kwargs(max_loss=500.0, underlying="AAPL"),
        cluster_exposure={"mega_cap_tech": 39_600.0},
    )
    assert not check.allowed
    assert any("mega_cap_tech" in r for r in check.reasons)


def test_cluster_cap_allows_when_under_it():
    check = risk_gate.check_new_spread(
        **_base_kwargs(max_loss=500.0, underlying="AAPL"),
        cluster_exposure={"mega_cap_tech": 1_000.0},
    )
    assert check.allowed


def test_cluster_cap_does_not_apply_to_uncovered_ticker():
    # SPY isn't in any cluster -- even a huge existing_exposure figure for
    # some cluster must never leak onto an unrelated, uncovered ticker.
    check = risk_gate.check_new_spread(
        **_base_kwargs(max_loss=500.0, underlying="SPY"),
        cluster_exposure={"mega_cap_tech": 99_000.0},
    )
    assert check.allowed


def test_cluster_cap_is_a_no_op_when_omitted():
    # Backward compatible: existing callers that never pass
    # cluster_exposure keep working exactly as before.
    check = risk_gate.check_new_spread(**_base_kwargs(max_loss=500.0, underlying="AAPL"))
    assert check.allowed


def test_cluster_cap_and_per_underlying_cap_are_independent_gates():
    # A candidate can pass the per-underlying cap (existing_exposure) but
    # still get blocked by the cluster cap, and vice versa -- both must be
    # checked, neither substitutes for the other.
    check = risk_gate.check_new_spread(
        **_base_kwargs(max_loss=500.0, underlying="MSFT"),
        existing_exposure={"MSFT": 0.0},  # this ticker alone is fine
        cluster_exposure={"mega_cap_tech": 39_600.0},  # but the cluster is nearly maxed
    )
    assert not check.allowed
    assert any("mega_cap_tech" in r for r in check.reasons)
