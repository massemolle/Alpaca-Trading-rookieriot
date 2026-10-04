"""Weekly A/B: credit-spread bot (sell premium) vs premium-buyer (buy premium),
both live on the same paper account since 2026-10-06. Run each Saturday.
Realized + open marks are account-truth; this just attributes by sleeve."""
from __future__ import annotations

import sys
from datetime import date

import db
import psycopg2.extras

SINCE = sys.argv[1] if len(sys.argv) > 1 else "2026-10-06"


def main():
    s = db._schema()
    with db._connection() as conn, conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        print(f"=== STRATEGY COMPARISON (since {SINCE}, as of {date.today()}) ===\n")

        cur.execute(f"""select count(*) n, count(*) filter (where realized_pnl>0) wins,
                        coalesce(sum(realized_pnl),0) realized
                        from {s}.spreads where closed_at >= %s""", (SINCE,))
        c = cur.fetchone()
        cur.execute(f"select count(*) o from {s}.spreads where status in ('open','pending')")
        print(f"CREDIT BOT (sell premium): {c['n']} closed, {c['wins']} wins, "
              f"realized ${float(c['realized']):.2f}, {cur.fetchone()['o']} open")

        cur.execute(f"""select count(*) n, count(*) filter (where realized_pnl>0) wins,
                        coalesce(sum(realized_pnl),0) realized
                        from {s}.premium_positions where closed_at >= %s""", (SINCE,))
        p = cur.fetchone()
        cur.execute(f"select count(*) o from {s}.premium_positions where status='open'")
        print(f"PREMIUM BUYER (buy premium): {p['n']} closed, {p['wins']} wins, "
              f"realized ${float(p['realized']):.2f}, {cur.fetchone()['o']} open")

        cur.execute(f"""select coalesce(avg(brier) filter (where taken),0) t,
                        coalesce(avg(brier) filter (where not taken),0) d, count(*) n
                        from {s}.premium_predictions where resolved_at is not null""")
        b = cur.fetchone()
        print(f"\nPREMIUM judge calibration (Brier, lower=better; coin=0.25): "
              f"taken {float(b['t']):.3f} / declined {float(b['d']):.3f} over {b['n']} resolved")

        cur.execute(f"""select policy, coalesce(sum(realized_pnl) filter (where status<>'open'),0) r
                        from {s}.shadow_positions where policy in ('shadow','random') group by policy""")
        print("\nCredit-bot ablation baselines (all-time):",
              {r['policy']: round(float(r['r']), 2) for r in cur.fetchall()})

        cur.execute(f"select equity from {s}.account_snapshots order by id desc limit 1")
        print(f"\nAccount equity (both sleeves + any manual): ${float(cur.fetchone()['equity']):.2f}")


if __name__ == "__main__":
    main()
