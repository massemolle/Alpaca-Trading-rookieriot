"""Shadow book — live ablation on the SAME executable candidate menu.

Policies:
- 'shadow': mechanical rule (selector.shadow_select)
- 'random': matched trade count AND aggregate max-loss budget to the LLM
- 'menu':   EVERY gate-approved candidate, picked or not — the full
            counterfactual menu, so the evening review can measure regret
            (profitable candidates the LLM dropped). Not an ablation arm:
            it is not risk-matched, so it must never be summed against the
            policy books above.

Virtual fills use the candidate's credit_estimate (conservative synthetic mid)
so policy attribution is comparable; real broker fills are reported separately
as execution quality on the live book.
"""
from __future__ import annotations

import logging
import os
import random
from datetime import date, datetime, timedelta

import db
import executor_mcp
import risk_gate
from selector import aggregate_max_loss

logger = logging.getLogger(__name__)


def _record_open(cycle_id: int, policy: str, cand: dict, plan, contracts: int, same_as_llm: bool) -> None:
    with db._connection() as conn, conn.cursor() as cur:
        cur.execute(
            f"""
            insert into {db._schema()}.shadow_positions
                (cycle_id, policy, underlying, direction, expiration, short_strike, long_strike,
                 short_symbol, long_symbol, contracts, credit_received, max_loss, status, same_as_llm)
            values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'open',%s)
            """,
            (cycle_id, policy, plan.underlying, plan.direction, plan.expiration.isoformat(),
             plan.short_strike, plan.long_strike, plan.short_symbol, plan.long_symbol,
             contracts, plan.credit_estimate, plan.max_loss, same_as_llm),
        )


def _get_open() -> list[dict]:
    import psycopg2.extras
    with db._connection() as conn, conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(f"select * from {db._schema()}.shadow_positions where status='open' order by opened_at")
        return list(cur.fetchall())


def _mark(row_id: int, mark: float) -> None:
    with db._connection() as conn, conn.cursor() as cur:
        cur.execute(
            f"update {db._schema()}.shadow_positions set unrealized_mark=%s where id=%s",
            (mark, row_id),
        )


def _close(row_id: int, status: str, realized_pnl: float | None) -> None:
    with db._connection() as conn, conn.cursor() as cur:
        cur.execute(
            f"""update {db._schema()}.shadow_positions
                set status=%s, realized_pnl=%s, closed_at=now(), unrealized_mark=NULL
                where id=%s""",
            (status, realized_pnl, row_id),
        )


def _pick_random_matched(
    candidates: list[dict],
    llm_selected: list[str],
    cycle_id: int,
) -> list[str]:
    """Match LLM on trade count and approximate aggregate max-loss budget."""
    by_ticker = {c["ticker"]: c for c in candidates}
    n_llm = len(llm_selected)
    if n_llm == 0 or not by_ticker:
        return []
    llm_risk = aggregate_max_loss(candidates, llm_selected)
    rng = random.Random(cycle_id)
    pool = sorted(by_ticker.keys())
    # Try several draws; keep the one closest under the LLM risk budget.
    best: list[str] = []
    best_gap = float("inf")
    for offset in range(20):
        rng_i = random.Random(cycle_id * 100_003 + offset)
        picks = rng_i.sample(pool, min(n_llm, len(pool)))
        risk = aggregate_max_loss(candidates, picks)
        if risk <= llm_risk + 1e-9:
            return picks
        gap = abs(risk - llm_risk)
        if gap < best_gap:
            best_gap = gap
            best = picks
    return best or rng.sample(pool, min(n_llm, len(pool)))


def open_counterfactuals(
    cycle_id: int,
    candidates: list[dict],
    llm_selected: list[str],
    shadow_selected: list[str],
    sizing_fn,
    equity: float,
    max_risk_pct: float,
) -> None:
    try:
        by_ticker = {c["ticker"]: c for c in candidates}
        random_selected = _pick_random_matched(candidates, llm_selected, cycle_id)

        for policy, picks in (("shadow", shadow_selected), ("random", random_selected)):
            for ticker in picks:
                cand = by_ticker.get(ticker)
                if cand is None or "_plan" not in cand:
                    continue
                plan = cand["_plan"]
                contracts = int(cand.get("contracts") or 0)
                if contracts < 1:
                    contracts = sizing_fn(
                        equity=equity,
                        max_loss_per_contract=plan.max_loss,
                        max_risk_pct=max_risk_pct,
                    )
                if contracts < 1:
                    continue
                _record_open(
                    cycle_id, policy, cand, plan, contracts,
                    same_as_llm=ticker in llm_selected,
                )
        logger.info(
            "shadow book: recorded shadow=%s random=%s (llm took %d)",
            shadow_selected, random_selected, len(llm_selected),
        )
    except Exception:
        logger.exception("shadow book open_counterfactuals failed (non-fatal)")


def _menu_open_symbol_pairs() -> set:
    with db._connection() as conn, conn.cursor() as cur:
        cur.execute(
            f"""select short_symbol, long_symbol from {db._schema()}.shadow_positions
                where policy='menu' and status='open'"""
        )
        return {(r[0], r[1]) for r in cur.fetchall()}


def open_menu_book(
    cycle_id: int,
    candidates: list[dict],
    llm_selected: list[str],
    sizing_fn,
    equity: float,
    max_risk_pct: float,
) -> None:
    """Virtually fill EVERY gate-approved candidate (policy='menu').

    Dedup on the open (short, long) symbol pair — an unchanged menu must not
    re-open the same spread every 30 minutes; a new episode starts only after
    the old virtual position closed. MENU_BOOK_MAX_OPEN caps marking load.
    """
    try:
        # Cap sized to the multi-day backlog: episodes stay open for days
        # (up to 14 DTE), so 20 was reached on 09-14 and 09-16 and silently
        # dropped the decision-cycle candidates regret exists to track.
        cap = int(os.environ.get("MENU_BOOK_MAX_OPEN", "40"))
        already = _menu_open_symbol_pairs()
        n_open = len(already)
        for cand in candidates:
            plan = cand.get("_plan")
            if plan is None:
                continue
            pair = (plan.short_symbol, plan.long_symbol)
            if pair in already:
                continue
            if n_open >= cap:
                logger.info("menu book: cap %d reached — skipping %s", cap, plan.underlying)
                continue
            contracts = int(cand.get("contracts") or 0)
            if contracts < 1:
                contracts = sizing_fn(
                    equity=equity,
                    max_loss_per_contract=plan.max_loss,
                    max_risk_pct=max_risk_pct,
                )
            if contracts < 1:
                continue
            _record_open(
                cycle_id, "menu", cand, plan, contracts,
                same_as_llm=cand.get("ticker") in llm_selected,
            )
            already.add(pair)
            n_open += 1
    except Exception:
        logger.exception("menu book open failed (non-fatal)")


def regret_summary(menu_rows: list[dict], capacity_cycles: set[int] | None = None) -> dict:
    """Pure regret computation for the evening context.

    outcome_usd per row: realized_pnl when closed; (credit − mark) × contracts
    while open and marked; None when never marked. 'Dropped' = the LLM did not
    take it (whatever the rule/random books did).

    capacity_cycles (D26, 2026-10-09): cycle ids screened menu-only while the
    real book sat at the concurrent cap. Their rows are flagged at_capacity
    and summed into the cap_window_* fields INSTEAD of dropped_* — the judge
    never saw those menus, so they price the cap, not the judge.
    """
    caps = capacity_cycles or set()
    table = []
    for r in menu_rows:
        credit = float(r["credit_received"])
        contracts = int(r.get("contracts") or 1)
        if r.get("realized_pnl") is not None:
            outcome = float(r["realized_pnl"])
        elif r.get("unrealized_mark") is not None:
            outcome = (credit - float(r["unrealized_mark"])) * contracts
        else:
            outcome = None
        table.append({
            "cycle_id": r.get("cycle_id"),
            "underlying": r.get("underlying"),
            "direction": r.get("direction"),
            "short_strike": float(r["short_strike"]) if r.get("short_strike") is not None else None,
            "long_strike": float(r["long_strike"]) if r.get("long_strike") is not None else None,
            "expiration": str(r.get("expiration")),
            "status": r.get("status"),
            "taken_by_llm": bool(r.get("same_as_llm")),
            "at_capacity": r.get("cycle_id") in caps,
            "outcome_usd": round(outcome, 2) if outcome is not None else None,
        })
    dropped = [t for t in table
               if not t["taken_by_llm"] and not t["at_capacity"] and t["outcome_usd"] is not None]
    taken = [t for t in table if t["taken_by_llm"] and t["outcome_usd"] is not None]
    dropped_pos = [t for t in dropped if t["outcome_usd"] > 0]
    cap_rows = [t for t in table if t["at_capacity"] and t["outcome_usd"] is not None]
    cap_pos = [t for t in cap_rows if t["outcome_usd"] > 0]
    return {
        "note": (
            "Every gate-approved candidate is virtually tracked (policy='menu'), picked or "
            "not. Regret = profitable candidates the LLM dropped. One lucky miss is noise — "
            "act on patterns, and read the journal's cited reasoning for those cycles first. "
            "cap_window_* rows (at_capacity) were screened menu-only while the book sat at "
            "the concurrent cap — the judge never saw them; they price the cap, not the judge."
        ),
        "rows": table,
        "taken_count": len(taken),
        "taken_total_usd": round(sum(t["outcome_usd"] for t in taken), 2),
        "dropped_count": len(dropped),
        "dropped_total_usd": round(sum(t["outcome_usd"] for t in dropped), 2),
        "dropped_positive_count": len(dropped_pos),
        "dropped_positive_total_usd": round(sum(t["outcome_usd"] for t in dropped_pos), 2),
        "best_dropped": max(dropped, key=lambda t: t["outcome_usd"], default=None),
        "cap_window_count": len(cap_rows),
        "cap_window_total_usd": round(sum(t["outcome_usd"] for t in cap_rows), 2),
        "cap_window_positive_count": len(cap_pos),
        "cap_window_positive_total_usd": round(sum(t["outcome_usd"] for t in cap_pos), 2),
    }


def ablation_totals(
    real_rows: list[dict],
    shadow_rows: list[dict],
    recent_days: int = 7,
    today: date | None = None,
) -> dict:
    """Closed-trade aggregates for the three-arm ablation (pure): all-time
    plus one shared recent clock window.

    Must be fed FULL-table rows, not the evening context's windowed lists:
    those are 'most recent N opens' per book, and because the rule book opens
    several times faster than the real book, its window reaches back a fraction
    as far — after a one-sided week the windows cover different regimes and a
    naive comparison inverts (observed 2026-09-21). Compare the arms here.

    All-time alone is not enough either: it never dilutes the early-era
    losses, so an arm that improved weeks ago can trail on the lifetime row
    indefinitely (the 09-21 review had to hand-compute a same-window
    comparison to see per-trade parity). recent_<N>d applies ONE cutoff —
    closed_at within the last recent_days — to every arm, so it is
    regime-fair by construction; rows closed without a closed_at (legacy)
    count all-time but never recent.

    expiry_unbooked_*: closed_expiry rows with realized_pnl None — closes
    settled without a broker fill, so no P&L was ever booked. These are
    NOT in closed_n/realized totals, and the censoring is asymmetric by
    mechanism: the real book's far-OTM winners can't fill mleg closes on
    quote-dead legs (0-for-7 since 09-23) and now ride to expiry
    settlement (D23), while its losers DO fill (near-money legs stay
    quoted, stops execute) and the virtual arms realize winners at mark
    with no fill needed. Left invisible, llm_real's realized totals keep
    every loss and drop expiry wins (TLT 35's +$74 on 09-29 was the
    first). expiry_unbooked_credit_usd is the ceiling of the missing
    P&L — exact when the spread expired fully OTM, which is what riding
    a winner to expiry means in practice.
    """
    cutoff = (today or date.today()) - timedelta(days=recent_days)
    recent_key = f"recent_{recent_days}d"
    arms = {"llm_real": real_rows}
    for policy in ("shadow", "random"):
        arms[policy] = [r for r in shadow_rows if r.get("policy") == policy]
    out = {
        "note": (
            "Closed-trade P&L per arm: all-time (window-free) plus "
            f"{recent_key} (closed_at within {recent_days} days — the SAME "
            "clock window for every arm, so it is regime-fair). Use these for "
            "the LLM-vs-rule-vs-random ablation — all-time for lifetime, "
            f"{recent_key} for the current judge; the row lists above are "
            "opened_at-windowed per book and not comparable across arms. "
            "expiry_unbooked_* = closed_expiry rows whose P&L was never "
            "booked (settled, no fill) — NOT in the realized totals; the "
            "credit sum is the ceiling of what the arm's totals are "
            "missing (exact for spreads that expired fully OTM). llm_real "
            "accumulates these on quote-dead winners, so read its realized "
            "totals alongside this column before comparing arms."
        ),
    }

    def _credit(r: dict) -> float:
        return float(r.get("credit_received") or 0) * int(r.get("contracts") or 1)

    for name, rows in arms.items():
        closed = [
            r for r in rows
            if str(r.get("status") or "").startswith("closed")
            and r.get("realized_pnl") is not None
        ]
        pnls = [float(r["realized_pnl"]) for r in closed]
        recent = [
            float(r["realized_pnl"]) for r in closed
            if r.get("closed_at") is not None and _to_date(r["closed_at"]) >= cutoff
        ]
        unbooked = [
            r for r in rows
            if r.get("status") == "closed_expiry" and r.get("realized_pnl") is None
        ]
        unbooked_recent = [
            r for r in unbooked
            if r.get("closed_at") is not None and _to_date(r["closed_at"]) >= cutoff
        ]
        out[name] = {
            "closed_n": len(pnls),
            "realized_total_usd": round(sum(pnls), 2),
            "avg_per_closed_usd": round(sum(pnls) / len(pnls), 2) if pnls else None,
            "open_n": sum(1 for r in rows if r.get("status") == "open"),
            "expiry_unbooked_n": len(unbooked),
            "expiry_unbooked_credit_usd": round(sum(_credit(r) for r in unbooked), 2),
            recent_key: {
                "closed_n": len(recent),
                "realized_total_usd": round(sum(recent), 2),
                "avg_per_closed_usd": round(sum(recent) / len(recent), 2) if recent else None,
                "expiry_unbooked_n": len(unbooked_recent),
                "expiry_unbooked_credit_usd": round(sum(_credit(r) for r in unbooked_recent), 2),
            },
        }
    return out


def resolved_dropped_cycles(regret_rows: list[dict], cap: int = 40) -> list[int]:
    """Cycle ids whose journal reasoning the evening review needs: menu
    episodes the LLM dropped that RESOLVED profitable. By resolution time the
    cycle usually sits outside journal_recent's window (c192/c193/c225 on
    09-16 and c242 on 09-21 all ended 'unclassifiable' that way), so the
    context builder re-fetches these journals explicitly. Newest first.

    The cap is a safety valve, NOT a recency filter: at cap=12 a rally week's
    fresh profitable drops crowded out the very cycles the review had flagged
    for classification — c242/c225/c193/c192/c142 all fell past the cap on
    2026-09-22, the first night this function ran. The input is already
    bounded by the menu query (100 newest rows ≈ a few dozen distinct
    cycles), so 40 means 'all of them' in practice while still bounding the
    context if the menu window ever widens."""
    out: list[int] = []
    for r in regret_rows:
        cid = r.get("cycle_id")
        if (
            cid is not None
            and not r.get("taken_by_llm")
            # at_capacity rows (D26) have no drop reasoning to classify —
            # their cycle's journal only holds the cap-skip message.
            and not r.get("at_capacity")
            and str(r.get("status") or "").startswith("closed")
            and (r.get("outcome_usd") or 0) > 0
            and cid not in out
        ):
            out.append(cid)
        if len(out) >= cap:
            break
    return out


async def manage_open(mcp) -> None:
    try:
        for row in _get_open():
            try:
                mark, two_sided = await executor_mcp.get_spread_mark_detail(
                    mcp, row["short_symbol"], row["long_symbol"]
                )
            except Exception:
                logger.exception("shadow mark failed for %s", row["id"])
                continue
            force, _force_reason = risk_gate.should_force_close(
                expiration=_as_date(row["expiration"])
            )
            if mark is None:
                if force:
                    _close(row["id"], "closed_expiry", None)
                continue
            # An ask-only (bid-less short) mark is as fictional for the
            # virtual books as it is for the real one (2026-09-25: a $250
            # at-open "mark" on a ~$25 spread) — don't store it as an
            # outcome, and don't let it realize a fake virtual stop; the
            # last honest mark stands until the book is two-sided again.
            if two_sided:
                _mark(row["id"], mark)
            close, _reason = risk_gate.should_close(
                credit_received=float(row["credit_received"]), current_mark=mark,
                short_leg_two_sided=two_sided,
            )
            if force and not two_sided:
                # Same rule as _mark above: never realize an ask-only mark.
                _close(row["id"], "closed_expiry", None)
                continue
            if close or force:
                contracts = int(row.get("contracts") or 1)
                realized = (float(row["credit_received"]) - mark) * contracts
                status = (
                    "closed_expiry" if force
                    else ("closed_profit" if realized > 0 else "closed_stop")
                )
                _close(row["id"], status, realized)
    except Exception:
        logger.exception("shadow book manage_open failed (non-fatal)")


def _as_date(value) -> date:
    if isinstance(value, date):
        return value
    return datetime.fromisoformat(str(value)).date()


def _to_date(value) -> date:
    # Unlike _as_date, normalizes datetimes to plain dates so the result is
    # always comparable against a date cutoff (psycopg2 hands back tz-aware
    # datetimes; the JSON round-trip hands back strings).
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return datetime.fromisoformat(str(value)).date()
