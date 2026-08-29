"""Mechanical selection baseline — one implementation for live shadow, lab,
and any offline ablation so the score rule cannot drift between surfaces.

Score = strength * (credit / max_loss). Higher is better.
"""
from __future__ import annotations

from typing import Any


def mechanical_score(candidate: dict[str, Any]) -> float:
    credit = float(candidate.get("credit_estimate") or 0)
    max_loss = float(candidate.get("max_loss") or 0)
    strength = float(candidate.get("strength") or 0)
    if max_loss <= 0:
        return 0.0
    return strength * (credit / max_loss)


def _position_max_loss(candidate: dict[str, Any]) -> float:
    """Total max loss for the sized position (per-contract × contracts)."""
    contracts = int(candidate.get("contracts") or 1)
    return float(candidate.get("max_loss") or 0) * max(contracts, 1)


def shadow_select(
    candidates: list[dict[str, Any]],
    remaining_budget: int,
    *,
    max_aggregate_loss: float | None = None,
) -> list[str]:
    """Rank by mechanical_score, pick top N within remaining concurrent slots
    and optional aggregate max-loss budget (matched to the LLM's risk take).
    """
    if not candidates or remaining_budget <= 0:
        return []
    scored = sorted(
        ((c["ticker"], mechanical_score(c), _position_max_loss(c)) for c in candidates),
        key=lambda x: x[1],
        reverse=True,
    )
    picked: list[str] = []
    risk_used = 0.0
    for ticker, _score, position_loss in scored:
        if len(picked) >= remaining_budget:
            break
        if max_aggregate_loss is not None and risk_used + position_loss > max_aggregate_loss + 1e-9:
            continue
        picked.append(ticker)
        risk_used += position_loss
    return picked


def aggregate_max_loss(candidates: list[dict[str, Any]], tickers: list[str]) -> float:
    by_ticker = {c["ticker"]: c for c in candidates}
    total = 0.0
    for t in tickers:
        cand = by_ticker.get(t)
        if cand is None:
            continue
        total += _position_max_loss(cand)
    return total
