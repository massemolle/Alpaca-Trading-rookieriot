"""Contract sizing — shared by the live book, pre-trade gate, and shadow book.

Quantity is computed BEFORE the final risk gate so concentration and buying
power are checked against the actual dollar exposure that would be submitted,
not a one-contract proxy.
"""
from __future__ import annotations


def optimal_contracts(
    equity: float,
    max_loss_per_contract: float,
    max_risk_pct: float = 0.02,
    *,
    max_contracts: int | None = None,
) -> int:
    """Size contracts so total max loss stays within the per-spread risk budget.

    Returns 0 when even one contract would exceed the budget — callers must
    treat 0 as a hard reject (never silently force a 1-contract oversize).
    """
    if max_loss_per_contract <= 0 or equity <= 0 or max_risk_pct <= 0:
        return 0
    dollar_budget = equity * max_risk_pct
    contracts = int(dollar_budget // max_loss_per_contract)
    if contracts < 1:
        return 0
    if max_contracts is not None:
        contracts = min(contracts, max_contracts)
    return contracts
