"""Correlation-cluster membership — a real gap the per-underlying
concentration cap (config.risk.max_concentration_pct) does NOT cover:
five concurrent spreads on five different mega-cap tech names are not
five independent bets during a broad selloff -- mega-cap tech pairwise
correlations are well documented to spike toward ~0.9 in stress (see e.g.
https://www.schwab.com/learn/story/every-breadth-you-take-market-
concentration-risks -- industry commentary, not a single peer-reviewed
figure, but the concentration phenomenon itself is uncontroversial).

Adapted 2026-08-30 from the sibling project (Alejdro83/alpaca-options-agent,
same hackathon team's other strategy instance) — same clusters, same "not
exhaustive" caveat, checked via risk_gate's cluster-exposure gate
(max_cluster_concentration_pct) alongside the existing per-underlying cap,
not instead of it.

This is deliberately NOT a full sector taxonomy -- building and maintaining
one is out of scope before the hackathon deadline. These are the clusters
whose correlation risk is both best-documented and most likely to actually
appear in a broad S&P 500 / Nasdaq 100 screening universe. A name matching
NO cluster here is simply not covered by this gate, not a claim it's
uncorrelated with anything.
"""
from __future__ import annotations

# "Magnificent Seven" plus the two other names most commonly cited
# alongside them for correlation purposes (AVGO, AMD -- both large-cap
# semiconductor names that move with the same AI/growth-tech factor).
MEGA_CAP_TECH: frozenset[str] = frozenset({
    "AAPL", "MSFT", "GOOGL", "GOOG", "AMZN", "META", "NVDA", "TSLA", "AVGO", "AMD",
})

# Big US banks/financials -- a textbook correlated group (rate-sensitivity,
# credit-cycle exposure, and simple sector-ETF co-movement via XLF/KBE all
# push these together in a broad move, well beyond idiosyncratic single-name
# risk).
BIG_BANKS: frozenset[str] = frozenset({
    "JPM", "BAC", "WFC", "C", "GS", "MS",
})

# Oil & gas majors/large-caps -- move together on the same commodity-price
# factor (crude/nat-gas prices), not idiosyncratic company news, for the
# large majority of their daily variance.
ENERGY_MAJORS: frozenset[str] = frozenset({
    "XOM", "CVX", "COP", "SLB", "OXY",
})

# Broad US index ETFs (added 2026-08-31, this instance's amendment on merge):
# SPY, QQQ and IWM overlap heavily -- QQQ is dominated by SPY's own largest
# names and IWM co-moves in any broad risk move -- so a book of verticals
# across all three is, in stress, ONE US-market bet, not three. This is our
# actual default universe: without this cluster the cap above only protects
# universes we don't trade. At current sizing (1 contract, ~$400 max loss,
# max 5 concurrent ≈ 2% of equity) the 40% cap cannot bind -- it exists so
# the book's true correlation is capped honestly, and so the cap scales
# automatically if sizing is ever raised.
US_INDEX_ETF: frozenset[str] = frozenset({
    "SPY", "QQQ", "IWM", "DIA", "VOO", "IVV", "VTI",
})

_CLUSTERS: dict[str, frozenset[str]] = {
    "mega_cap_tech": MEGA_CAP_TECH,
    "big_banks": BIG_BANKS,
    "energy_majors": ENERGY_MAJORS,
    "us_index_etf": US_INDEX_ETF,
}


def cluster_for(ticker: str) -> str | None:
    """Which correlation cluster `ticker` belongs to, or None if it isn't
    in any defined cluster -- callers must treat None as "no cluster gate
    applies to this ticker", not as a rejection.
    """
    for name, members in _CLUSTERS.items():
        if ticker in members:
            return name
    return None
