import { type KpiSummary } from '@/lib/stats';

// Four stat tiles — label always in muted text, the number in primary
// text, and color reserved for the one figure that's inherently signed
// (P&L) so it never doubles as decoration on the others.
function Tile({ label, value, sub, tone }: { label: string; value: string; sub?: string; tone?: 'good' | 'bad' | 'neutral' }) {
  const valueColor = tone === 'good' ? 'text-emerald-400' : tone === 'bad' ? 'text-red-400' : 'text-white';
  return (
    <div className="rounded-lg border border-gray-800 bg-gray-900/30 p-3">
      <p className="text-[11px] uppercase tracking-wide text-gray-500">{label}</p>
      <p className={`text-lg font-bold ${valueColor}`}>{value}</p>
      {sub && <p className="text-[11px] text-gray-500 mt-0.5">{sub}</p>}
    </div>
  );
}

export function KpiRow({ kpis, vsSpy }: { kpis: KpiSummary; vsSpy?: number | null }) {
  const pnlTone = kpis.totalRealizedPnl > 0 ? 'good' : kpis.totalRealizedPnl < 0 ? 'bad' : 'neutral';
  const pnlSign = kpis.totalRealizedPnl >= 0 ? '+' : '';

  return (
    <div className={`grid grid-cols-2 ${vsSpy == null ? "sm:grid-cols-4" : "sm:grid-cols-5"} gap-2 mb-4`}>
      <Tile
        label="Realized P&L"
        value={`${pnlSign}$${kpis.totalRealizedPnl.toFixed(2)}`}
        sub={`${pnlSign}${(kpis.totalRealizedPnlPct * 100).toFixed(2)}% of starting capital`}
        tone={pnlTone}
      />
      <Tile
        label="Win rate"
        value={kpis.winRate === null ? '—' : `${(kpis.winRate * 100).toFixed(0)}%`}
        sub={kpis.closedCount > 0 ? `${kpis.closedCount} closed` : 'no closes yet'}
      />
      <Tile
        label="Trades"
        value={String(kpis.closedCount + kpis.openCount)}
        sub={`${kpis.openCount} open · ${kpis.closedCount} closed`}
      />
      <Tile
        label="Avg P&L / trade"
        value={kpis.avgPnlPerTrade === null ? '—' : `${kpis.avgPnlPerTrade >= 0 ? '+' : ''}$${kpis.avgPnlPerTrade.toFixed(2)}`}
        tone={kpis.avgPnlPerTrade === null ? 'neutral' : kpis.avgPnlPerTrade > 0 ? 'good' : kpis.avgPnlPerTrade < 0 ? 'bad' : 'neutral'}
      />
      {vsSpy != null && (
        <Tile
          label="vs SPY"
          value={`${vsSpy >= 0 ? '+' : ''}${(vsSpy * 100).toFixed(2)}%`}
          sub="account return − SPY return"
          tone={vsSpy > 0 ? 'good' : vsSpy < 0 ? 'bad' : 'neutral'}
        />
      )}
    </div>
  );
}
