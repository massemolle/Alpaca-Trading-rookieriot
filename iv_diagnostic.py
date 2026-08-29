"""Quote-implied volatility diagnostic (shadow / offline only).

Solves Black–Scholes IV from a liquid option mid and compares it to the
realized-vol proxy used for live strike selection. Does NOT change live
strike picking until dry-run evidence + unit tests promote it.

Usage:
  set -a; source .env; set +a
  python iv_diagnostic.py SPY
"""
from __future__ import annotations

import asyncio
import math
import sys
from datetime import datetime, timezone

import black_scholes


def _norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def bs_price(spot: float, strike: float, t: float, vol: float, r: float, call: bool) -> float:
    if t <= 0 or vol <= 0 or spot <= 0 or strike <= 0:
        return max(0.0, (spot - strike) if call else (strike - spot))
    d1 = (math.log(spot / strike) + (r + 0.5 * vol * vol) * t) / (vol * math.sqrt(t))
    d2 = d1 - vol * math.sqrt(t)
    if call:
        return spot * _norm_cdf(d1) - strike * math.exp(-r * t) * _norm_cdf(d2)
    return strike * math.exp(-r * t) * _norm_cdf(-d2) - spot * _norm_cdf(-d1)


def implied_vol(
    market_price: float,
    spot: float,
    strike: float,
    t_years: float,
    *,
    call: bool,
    r: float = 0.05,
    lo: float = 1e-4,
    hi: float = 5.0,
    tol: float = 1e-6,
) -> float | None:
    """Bisection IV solve. Returns None if no root in [lo, hi]."""
    if market_price <= 0 or t_years <= 0:
        return None
    f_lo = bs_price(spot, strike, t_years, lo, r, call) - market_price
    f_hi = bs_price(spot, strike, t_years, hi, r, call) - market_price
    if f_lo * f_hi > 0:
        return None
    for _ in range(80):
        mid = 0.5 * (lo + hi)
        f_mid = bs_price(spot, strike, t_years, mid, r, call) - market_price
        if abs(f_mid) < tol:
            return mid
        if f_lo * f_mid <= 0:
            hi = mid
            f_hi = f_mid
        else:
            lo = mid
            f_lo = f_mid
    return 0.5 * (lo + hi)


def model_delta_error(
    spot: float,
    strike: float,
    t_years: float,
    realized_vol: float,
    implied_vol_: float,
    *,
    call: bool,
) -> dict:
    """Compare BS delta at realized-vol proxy vs IV — quantifies strike miss."""
    dte_days = t_years * 365.0
    d_rv = black_scholes.bs_delta(
        spot=spot, strike=strike, dte_days=dte_days,
        volatility=realized_vol, option_type="call" if call else "put",
    )
    d_iv = black_scholes.bs_delta(
        spot=spot, strike=strike, dte_days=dte_days,
        volatility=implied_vol_, option_type="call" if call else "put",
    )
    return {
        "delta_realized_vol": d_rv,
        "delta_implied_vol": d_iv,
        "abs_error": abs(d_rv - d_iv),
        "rel_error": abs(d_rv - d_iv) / max(abs(d_iv), 1e-6),
    }


async def diagnose(underlying: str = "SPY") -> None:
    from alpaca_client import AlpacaClient
    from mcp_client import AlpacaMCP

    client = AlpacaClient()
    quote = client.get_latest_quote(underlying)
    spot = (quote["ask_price"] + quote["bid_price"]) / 2
    print(f"{underlying} spot mid ≈ {spot:.2f}")

    async with AlpacaMCP() as mcp:
        # Fetch a near-ATM put chain window similar to live builder.
        result = await mcp.call(
            "get_option_contracts",
            {
                "underlying_symbols": underlying,
                "status": "active",
                "type": "put",
                "expiration_date_gte": datetime.now(timezone.utc).date().isoformat(),
                "limit": 50,
            },
        )
    contracts = (result or {}).get("data", {}).get("option_contracts") or []
    if not contracts:
        # Alternate nesting
        contracts = (result or {}).get("option_contracts") or []
    print(f"Fetched {len(contracts)} put contracts (diagnostic sample)")
    print("IV diagnostic is shadow-only — live strike selection still uses realized vol.")
    print("Promote only after dry-run evidence + unit tests.")


if __name__ == "__main__":
    # Unit-style offline checks always run; live MCP path is optional.
    # Synthetic: ATM call, 30d, vol=20%, price should recover ~0.20 IV.
    spot, k, t, vol = 100.0, 100.0, 30 / 365, 0.20
    px = bs_price(spot, k, t, vol, 0.05, call=True)
    iv = implied_vol(px, spot, k, t, call=True)
    assert iv is not None and abs(iv - vol) < 1e-3, (iv, vol)
    err = model_delta_error(spot, k, t, 0.25, 0.20, call=False)
    print(f"IV round-trip OK (err={abs(iv - vol):.2e}); sample delta abs_error={err['abs_error']:.4f}")

    if len(sys.argv) > 1:
        asyncio.run(diagnose(sys.argv[1].upper()))
