"""The second risk gate (PLAN D1/ADR-0002): last-second validation AFTER the
LLM selects and BEFORE any order reaches Alpaca.

Hardened for quantity-aware sizing: contracts are computed inside the gate
from fresh equity/max_loss, then buying power and concentration are checked
against total exposure (max_loss * contracts), not a one-contract proxy.

Also fail-closed on missing quote timestamps (unknown age ≠ fresh).
"""
from __future__ import annotations

import dataclasses
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

import db
import risk_gate
from config import config
from screening import correlation_clusters
from sizing import optimal_contracts
from spread_builder import SpreadPlan, _mid_from_snapshot

logger = logging.getLogger(__name__)

STALE_QUOTE_MAX_MIN = 15
CREDIT_SHRINK_MAX = 0.20


@dataclass
class GateResult:
    allowed: bool
    reasons: list[str]
    plan: SpreadPlan
    facts: dict = field(default_factory=dict)
    contracts: int = 0

    @property
    def reason(self) -> str | None:
        return "; ".join(self.reasons) if self.reasons else None


def _daily_pl(account: dict) -> tuple[float, float]:
    equity = float(account["equity"])
    last_equity = float(account["last_equity"])
    pl = equity - last_equity
    pl_pct = pl / last_equity if last_equity else 0.0
    return pl, pl_pct


def _quote_age(snap: dict, now: datetime) -> timedelta | None:
    ts_str = snap.get("latestQuote", {}).get("t")
    if not ts_str:
        return None
    try:
        quote_ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None
    return now - quote_ts


async def pre_trade_check(
    mcp,
    client,
    plan: SpreadPlan,
    *,
    opened_this_cycle: int = 0,
    contracts: int | None = None,
) -> GateResult:
    try:
        return await _pre_trade_check_inner(
            mcp, client, plan, opened_this_cycle, contracts=contracts,
        )
    except Exception as exc:  # fail-closed
        logger.exception("Pre-trade gate errored — blocking the trade")
        return GateResult(False, [f"gate error (fail-closed): {exc}"], plan)


async def _pre_trade_check_inner(
    mcp, client, plan: SpreadPlan, opened_this_cycle: int, *, contracts: int | None,
) -> GateResult:
    facts: dict = {"checked_at": datetime.now(timezone.utc).isoformat()}

    result = await mcp.call(
        "get_option_snapshot",
        {"symbols": f"{plan.short_symbol},{plan.long_symbol}", "feed": "indicative"},
    )
    snap_by_symbol = (result or {}).get("data", {}).get("snapshots", {})
    short_snap = snap_by_symbol.get(plan.short_symbol, {})
    long_snap = snap_by_symbol.get(plan.long_symbol, {})

    short_mid = _mid_from_snapshot(short_snap)
    long_mid = _mid_from_snapshot(long_snap)
    if short_mid is None or long_mid is None:
        return GateResult(False, ["fresh quotes unavailable for one or both legs"], plan, facts)

    now = datetime.now(timezone.utc)
    for label, snap in [("short", short_snap), ("long", long_snap)]:
        age = _quote_age(snap, now)
        facts[f"{label}_quote_age_s"] = round(age.total_seconds(), 1) if age is not None else None
        if age is None:
            return GateResult(
                False,
                [f"{label} leg quote has no timestamp — unknown age, refusing to trade"],
                plan, facts,
            )
        if age > timedelta(minutes=STALE_QUOTE_MAX_MIN):
            return GateResult(
                False,
                [f"{label} leg quote is {age} old (>{STALE_QUOTE_MAX_MIN} min) — stale, refusing to trade on it"],
                plan, facts,
            )

    fresh_credit = round((short_mid - long_mid) * 100, 2)
    facts["original_credit"] = plan.credit_estimate
    facts["fresh_credit"] = fresh_credit
    if fresh_credit <= 0:
        return GateResult(False, [f"fresh credit is non-positive (${fresh_credit:.2f})"], plan, facts)

    shrink_pct = (plan.credit_estimate - fresh_credit) / plan.credit_estimate
    if shrink_pct > CREDIT_SHRINK_MAX:
        return GateResult(
            False,
            [f"credit shrank {shrink_pct:.0%} (original ${plan.credit_estimate:.2f} → fresh ${fresh_credit:.2f})"],
            plan, facts,
        )

    width_dollars = abs(plan.short_strike - plan.long_strike) * 100
    updated_max_loss = round(width_dollars - fresh_credit, 2)
    if updated_max_loss <= 0:
        return GateResult(
            False, [f"fresh max_loss is non-positive (${updated_max_loss:.2f}), refusing to trade"], plan, facts
        )
    updated_plan = dataclasses.replace(plan, credit_estimate=fresh_credit, max_loss=updated_max_loss)

    account = client.get_account()
    _, daily_pl_pct = _daily_pl(account)
    equity = float(account["equity"])
    fresh_open = db.get_open_spreads()
    open_count = len(fresh_open) + opened_this_cycle
    existing_exposure: dict[str, float] = {}
    cluster_exposure: dict[str, float] = {}
    for s in fresh_open:
        u = s["underlying"]
        n = int(s.get("contracts") or 1)
        max_loss_total = float(s.get("max_loss", 0)) * n
        existing_exposure[u] = existing_exposure.get(u, 0) + max_loss_total
        cluster = correlation_clusters.cluster_for(u)
        if cluster is not None:
            cluster_exposure[cluster] = cluster_exposure.get(cluster, 0) + max_loss_total

    if contracts is None:
        contracts = optimal_contracts(
            equity=equity,
            max_loss_per_contract=updated_max_loss,
            max_risk_pct=config.risk.max_loss_per_spread_pct,
            max_contracts=config.risk.max_contracts_per_spread,
        )
    facts["contracts"] = contracts
    facts["equity_at_check"] = equity
    facts["buying_power_at_check"] = float(account.get("buying_power") or 0.0)
    facts["open_count_used"] = open_count
    facts["opened_this_cycle"] = opened_this_cycle

    if contracts < 1:
        return GateResult(
            False,
            [f"even 1 contract max loss ${updated_max_loss:,.2f} exceeds "
             f"{config.risk.max_loss_per_spread_pct:.0%} of equity"],
            updated_plan, facts, contracts=0,
        )

    total_max_loss = updated_max_loss * contracts
    facts["total_max_loss"] = total_max_loss

    if facts["buying_power_at_check"] < total_max_loss:
        return GateResult(
            False,
            [f"buying power ${facts['buying_power_at_check']:,.2f} below "
             f"{contracts} contract(s) max loss ${total_max_loss:,.2f}"],
            updated_plan, facts, contracts=contracts,
        )

    check = risk_gate.check_new_spread(
        equity=equity,
        daily_pl_pct=daily_pl_pct,
        open_spreads_count=open_count,
        max_loss=total_max_loss,
        expiration=plan.expiration,
        today=now.date(),
        existing_exposure=existing_exposure,
        underlying=plan.underlying,
        cluster_exposure=cluster_exposure,
    )
    if not check.allowed:
        return GateResult(
            False,
            [f"risk gate rejected on fresh quotes: {r}" for r in check.reasons],
            updated_plan, facts, contracts=contracts,
        )

    return GateResult(True, [], updated_plan, facts, contracts=contracts)
