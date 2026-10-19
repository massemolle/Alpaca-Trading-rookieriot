"""Builds state/evening_context.json — everything the nightly engineer
(Fable) needs to review the day: decisions, positions, ablation, lab.
Read-only; run by run_evening_review.sh before the Fable session starts.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import psycopg2.extras

import db
import shadow_book


def _q(cur, sql: str) -> list[dict]:
    cur.execute(sql)
    return [dict(r) for r in cur.fetchall()]


def _day_metrics(bars: list[dict]) -> dict:
    """Objective end-of-day metrics from daily bars (oldest→newest applied
    internally). Pure computation — unit-tested offline."""
    import math

    bars = sorted(bars, key=lambda b: b["timestamp"])
    if len(bars) < 2:
        return {}
    last, prev = bars[-1], bars[-2]
    closes = [float(b["close"]) for b in bars]
    rets = [math.log(closes[i] / closes[i - 1]) for i in range(1, len(closes))][-20:]
    vol = None
    if len(rets) >= 5:
        mean = sum(rets) / len(rets)
        var = sum((r - mean) ** 2 for r in rets) / (len(rets) - 1)
        vol = round(math.sqrt(var) * math.sqrt(252) * 100, 2)
    vols20 = [int(b["volume"]) for b in bars[-21:-1]]
    return {
        "date": str(last["timestamp"])[:10],
        "close": float(last["close"]),
        "day_move_pct": round((float(last["close"]) / float(prev["close"]) - 1) * 100, 2),
        "gap_open_pct": round((float(last["open"]) / float(prev["close"]) - 1) * 100, 2),
        "day_range_pct": round((float(last["high"]) - float(last["low"])) / float(prev["close"]) * 100, 2),
        "volume_vs_20d": round(int(last["volume"]) / (sum(vols20) / len(vols20)), 2) if vols20 else None,
        "realized_vol_20d_pct_annualized": vol,
    }


# Which broker symbols each sleeve's live DB rows claim. All four arms trade
# the SAME paper account, and the credit bot's circuit breaker / drawdown halt
# key off ACCOUNT equity — so a loss in any sleeve halts this one. Attribution
# makes every such trip auditable at evening review (2026-10-19: entries were
# halted all day by a -3.3% account move the credit book's ~$2.9k total max
# loss could not have produced on its own).
_SLEEVE_TABLES = {
    "credit_bot": ("spreads", ["short_symbol", "long_symbol",
                               "call_short_symbol", "call_long_symbol"]),
    "premium_buyer": ("premium_positions", ["symbol"]),
    "killswitch": ("ks_positions", ["symbol"]),
    "council": ("council_positions", ["symbol"]),
}
_LIVE_STATUSES = ["open", "pending", "pending_close"]


def _attribute_positions(positions: list[dict], sleeve_symbols: dict) -> dict:
    """Pure: partition broker positions into sleeves by symbol ownership.
    First claimant in dict order wins a contested symbol; positions no sleeve
    claims (e.g. manual experiments' legs) land in 'unattributed'. Sums are
    broker marks — unrealized_intraday_pl is today's move vs yesterday's
    close (None from older callers counts as 0)."""
    buckets = {
        sleeve: {"n": 0, "symbols": [], "market_value": 0.0,
                 "unrealized_pl": 0.0, "unrealized_intraday_pl": 0.0}
        for sleeve in [*sleeve_symbols, "unattributed"]
    }
    for p in positions:
        sym = p.get("symbol")
        target = next((sl for sl, syms in sleeve_symbols.items() if sym in syms),
                      "unattributed")
        b = buckets[target]
        b["n"] += 1
        b["symbols"].append(sym)
        b["market_value"] += float(p.get("market_value") or 0.0)
        b["unrealized_pl"] += float(p.get("unrealized_pl") or 0.0)
        b["unrealized_intraday_pl"] += float(p.get("unrealized_intraday_pl") or 0.0)
    for b in buckets.values():
        for k in ("market_value", "unrealized_pl", "unrealized_intraday_pl"):
            b[k] = round(b[k], 2)
    return buckets


def _sleeve_attribution() -> dict:
    """Decompose the shared account's daily P&L by sleeve: broker positions
    bucketed by which sleeve's live DB rows claim the symbol, plus each
    sleeve's realized P&L booked today. Own connection and fail-soft
    throughout — a missing arm table or a broker error must not sink the
    context build (and must not poison the main transaction)."""
    sleeve_symbols: dict[str, set] = {}
    realized_today: dict[str, float] = {}
    try:
        with db._connection() as conn, conn.cursor() as cur:
            s = db._schema()
            for sleeve, (table, cols) in _SLEEVE_TABLES.items():
                try:
                    cur.execute(
                        f"""select {', '.join(cols)} from {s}.{table}
                            where status = any(%s)""",
                        (_LIVE_STATUSES,),
                    )
                    sleeve_symbols[sleeve] = {
                        v for row in cur.fetchall() for v in row if v
                    }
                    cur.execute(
                        f"""select coalesce(sum(realized_pnl), 0) from {s}.{table}
                            where closed_at::date = current_date""",
                    )
                    realized_today[sleeve] = float(cur.fetchone()[0])
                except Exception as exc:  # e.g. arm table not created yet
                    conn.rollback()
                    sleeve_symbols[sleeve] = set()
                    realized_today[sleeve] = 0.0
                    realized_today[f"{sleeve}_error"] = str(exc)[:200]
    except Exception as exc:
        return {"error": f"sleeve_attribution unavailable (db): {exc}"}
    try:
        from alpaca_client import AlpacaClient

        client = AlpacaClient()
        acct = client.get_account()
        positions = client.get_positions()
    except Exception as exc:
        return {"error": f"sleeve_attribution unavailable (broker): {exc}",
                "realized_today": realized_today}
    return {
        "note": "The circuit breaker and drawdown halt react to ACCOUNT daily "
                "P&L, shared by all four sleeves. unrealized_intraday_pl is "
                "each bucket's share of today's move (broker marks vs "
                "yesterday close); realized_today is per-sleeve booked P&L. "
                "account.daily_pl ≈ sum of bucket intraday marks + realized "
                "fills; 'unattributed' = broker positions no sleeve's live "
                "rows claim. Marks, not fills — same caveat as menu outcomes.",
        "account": {
            "equity": acct["equity"],
            "last_equity": acct["last_equity"],
            "daily_pl": round(acct["equity"] - acct["last_equity"], 2),
            "cash": acct["cash"],
        },
        "buckets": _attribute_positions(positions, sleeve_symbols),
        "realized_today": realized_today,
    }


def _market_day() -> dict:
    """What the market actually did today, per universe ticker — fetched from
    our own broker API at context-build time (credentials are still in the
    env here; they are scrubbed only for the engineer session that reads the
    resulting file). This is the engineer's substitute for 'reading the
    news': bounded, sourced, reproducible numbers instead of feeds."""
    try:
        from datetime import timedelta

        from alpaca.data.timeframe import TimeFrame

        from alpaca_client import AlpacaClient
        from config import config

        client = AlpacaClient()
        start = (datetime.now(timezone.utc) - timedelta(days=70)).strftime("%Y-%m-%d")
        out = {}
        for t in config.universe.tickers:
            try:
                out[t] = _day_metrics(client.get_bars(t, TimeFrame.Day, start=start, limit=60))
            except Exception as exc:  # one bad ticker must not sink the section
                out[t] = {"error": str(exc)}
        return out
    except Exception as exc:
        return {"error": f"market_day unavailable: {exc}"}


def main() -> None:
    s = db._schema()
    with db._connection() as conn, conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        ctx = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            # A full session is 15 half-hour cycles (13:30-20:30Z), and the
            # cycles table gains an extra row per opened spread on multi-open
            # cycles; limit 12 dropped the morning on 09-15 and 09-16.
            "cycles_recent": _q(cur, f"select id, decision, reasoning, error, ran_at from {s}.cycles order by id desc limit 20"),
            "journal_recent": _q(cur, f"""select cycle_id, candidates, llm_selected, llm_reasoning,
                                          shadow_selected, gate_rejections, pre_trade_rejections, created_at
                                          from {s}.decision_journal order by id desc limit 16"""),
            "spreads_all": _q(cur, f"select * from {s}.spreads order by opened_at desc limit 30"),
            "shadow_positions": _q(cur, f"""select * from {s}.shadow_positions
                                           where policy in ('shadow','random')
                                           order by opened_at desc limit 60"""),
            # Window-free: the row lists above are 'most recent N opens' per
            # book, and the rule book opens several times faster than the real
            # one — after a one-sided week their windows cover different
            # regimes and a naive cross-book comparison inverts (2026-09-21).
            "ablation_totals": shadow_book.ablation_totals(
                _q(cur, f"""select status, realized_pnl, closed_at,
                            credit_received, contracts from {s}.spreads"""),
                _q(cur, f"""select policy, status, realized_pnl, closed_at,
                            credit_received, contracts
                            from {s}.shadow_positions
                            where policy in ('shadow','random')"""),
            ),
            "menu_regret": shadow_book.regret_summary(
                _q(cur, f"""select * from {s}.shadow_positions where policy='menu'
                            order by opened_at desc limit 100"""),
                # D26: cycles screened menu-only at the concurrent cap. A
                # 'skipped' decision with a non-empty candidates array is
                # that path's unique signature — every other candidate-
                # bearing path ends opened/abstained/gate_blocked/error.
                capacity_cycles={
                    r["id"] for r in _q(cur, f"""select id from {s}.cycles
                        where decision = 'skipped'
                        and jsonb_array_length(candidates) > 0""")
                },
            ),
            "snapshots_recent": _q(cur, f"select * from {s}.account_snapshots order by snapshot_at desc limit 10"),
            "lab_summary": _q(cur, f"select * from {s}.lab_summary order by id"),
        }
        # Resolved profitable drops must be classifiable from their cited
        # reasoning, but by resolution time the cycle has usually aged out of
        # journal_recent (c192/c193/c225 on 09-16, c242 on 09-21). Re-fetch
        # exactly those journals; bounded by resolved_dropped_cycles' cap.
        wanted = shadow_book.resolved_dropped_cycles(ctx["menu_regret"]["rows"])
        if wanted:
            cur.execute(
                f"""select distinct on (cycle_id) cycle_id, llm_reasoning
                    from {s}.decision_journal where cycle_id = any(%s)
                    order by cycle_id desc""",
                (wanted,),
            )
            ctx["menu_regret"]["resolved_dropped_journal"] = {
                str(r["cycle_id"]): r["llm_reasoning"] for r in cur.fetchall()
            }
    ctx["market_day"] = _market_day()
    ctx["sleeve_attribution"] = _sleeve_attribution()
    # Feed the previous session back in — especially a REVERTED one: the next
    # engineer must see what was tried and which tests it broke, or it will
    # repeat the same mistake nightly (learned from the first live run, where
    # a good idea — a credit-to-width floor — was reverted for breaking the
    # fill-confirmation sign tests).
    state = Path(__file__).resolve().parent / "state"
    prev_review = state / "evening_review_last.md"
    prev_gate = state / "evening_gate.log"
    ctx["previous_session"] = {
        "review": prev_review.read_text()[-6000:] if prev_review.exists() else None,
        "gate_log_tail": prev_gate.read_text()[-3000:] if prev_gate.exists() else None,
    }
    out = Path(__file__).resolve().parent / "state" / "evening_context.json"
    out.write_text(json.dumps(ctx, indent=1, default=str))
    print(f"context written: {out} ({out.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
