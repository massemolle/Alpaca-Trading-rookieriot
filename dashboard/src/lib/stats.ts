// Pure KPI calculations over the same `spreads` array page.tsx already
// fetches — no new API calls, just aggregation the dashboard wasn't doing
// before. Kept separate from page.tsx so the math is testable and the
// component stays about rendering, not arithmetic.

export interface SpreadForStats {
  status: string;
  realized_pnl: number | null;
}

// The hackathon's dedicated account started at exactly $100,000 (verified
// against the real account 2026-08-26) — used as the fixed denominator for
// a "% of starting capital" figure, since equity itself moves as spreads
// close and isn't the right base for that specific number.
export const STARTING_EQUITY = 100_000;

export interface KpiSummary {
  totalRealizedPnl: number;
  totalRealizedPnlPct: number;
  closedCount: number;
  openCount: number;
  winRate: number | null; // null when there's nothing closed yet to rate
  avgPnlPerTrade: number | null;
}

export function computeKpis(spreads: SpreadForStats[]): KpiSummary {
  const closed = spreads.filter((s) => s.status !== 'open' && s.realized_pnl !== null);
  const open = spreads.filter((s) => s.status === 'open');
  const totalRealizedPnl = closed.reduce((sum, s) => sum + Number(s.realized_pnl), 0);
  const wins = closed.filter((s) => Number(s.realized_pnl) > 0).length;

  return {
    totalRealizedPnl,
    totalRealizedPnlPct: totalRealizedPnl / STARTING_EQUITY,
    closedCount: closed.length,
    openCount: open.length,
    winRate: closed.length > 0 ? wins / closed.length : null,
    avgPnlPerTrade: closed.length > 0 ? totalRealizedPnl / closed.length : null,
  };
}

export interface CurvePoint {
  equity: number | string;
  spy_price: number | string | null;
  snapshot_at: string;
}

// "Skill vs market": account return minus SPY buy-and-hold return, both
// measured from the first snapshot that has a SPY price. Postgres numerics
// arrive as strings — coerce everything.
export function computeVsSpy(curve: CurvePoint[]): number | null {
  const withSpy = curve.filter((p) => p.spy_price !== null && Number(p.spy_price) > 0);
  if (withSpy.length < 2) return null;
  const first = withSpy[0];
  const last = withSpy[withSpy.length - 1];
  const acctReturn = Number(last.equity) / Number(first.equity) - 1;
  const spyReturn = Number(last.spy_price) / Number(first.spy_price) - 1;
  return acctReturn - spyReturn;
}
