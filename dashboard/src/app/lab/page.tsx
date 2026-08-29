'use client';

// The Lab: full inspectable history of the incremental backtest — every
// simulated trade behind the summary numbers, filterable by config. This is
// the "why would I trust you" page: same data, drill-down instead of claims.
import { useEffect, useState } from 'react';
import { Shell } from '@/components/Shell';

interface SummaryRow {
  config: string; n_trades: number; total_pnl: string; win_rate: string;
  avg_pnl: string; max_drawdown: string; run_at: string;
}
interface TradeRow {
  config: string; symbol: string; direction: string; entry_date: string;
  exit_date: string; credit: string; pnl: string; exit_reason: string;
}

export default function LabPage() {
  const [summary, setSummary] = useState<SummaryRow[]>([]);
  const [trades, setTrades] = useState<TradeRow[]>([]);
  const [filter, setFilter] = useState<string>('all');
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetch('/api/lab')
      .then((r) => r.json())
      .then((d) => { setSummary(d.summary ?? []); setTrades(d.trades ?? []); })
      .catch(() => setError('Failed to load lab data'));
  }, []);

  const configs = Array.from(new Set(trades.map((t) => t.config)));
  const shown = filter === 'all' ? trades : trades.filter((t) => t.config === filter);

  return (
    <Shell>
      <div className="flex items-baseline justify-between mb-3">
        <h1 className="text-lg font-bold">Lab — backtest incremental</h1>
        <a href="/" className="text-xs text-gray-400 underline">← dashboard</a>
      </div>
      <p className="text-xs text-gray-500 mb-4">
        Cada capa de la estrategia medida por separado sobre ~16 meses de barras
        diarias reales. Economía de spreads con proxy Black-Scholes (sin cadenas
        históricas en el plan gratuito): comparaciones RELATIVAS entre configs,
        nunca afirmaciones absolutas de rendimiento. Código: backtest_lab.py.
      </p>

      {error && <p className="text-red-400 text-sm">{error}</p>}

      <section className="mb-5">
        <h2 className="text-sm font-semibold text-gray-300 mb-2">Escalera de componentes</h2>
        <div className="overflow-x-auto rounded-lg border border-gray-800">
          <table className="w-full text-sm">
            <thead className="bg-gray-900/60 text-gray-400 text-xs">
              <tr>
                <th className="text-left p-2">config</th><th className="text-right p-2">trades</th>
                <th className="text-right p-2">P&L total</th><th className="text-right p-2">win%</th>
                <th className="text-right p-2">medio</th><th className="text-right p-2">max DD</th>
              </tr>
            </thead>
            <tbody>
              {summary.map((s) => {
                const pnl = Number(s.total_pnl);
                return (
                  <tr key={s.config} className="border-t border-gray-800/60">
                    <td className="p-2 text-gray-200">{s.config}</td>
                    <td className="p-2 text-right text-gray-400">{s.n_trades}</td>
                    <td className={`p-2 text-right font-semibold ${pnl > 0 ? 'text-emerald-400' : 'text-red-400'}`}>
                      {pnl >= 0 ? '+' : ''}${pnl.toFixed(2)}
                    </td>
                    <td className="p-2 text-right text-gray-300">{(Number(s.win_rate) * 100).toFixed(1)}%</td>
                    <td className="p-2 text-right text-gray-300">${Number(s.avg_pnl).toFixed(2)}</td>
                    <td className="p-2 text-right text-gray-400">${Number(s.max_drawdown).toFixed(2)}</td>
                  </tr>
                );
              })}
              {summary.length === 0 && !error && (
                <tr><td className="p-3 text-gray-500" colSpan={6}>Sin datos aún — ejecuta backtest_lab.py</td></tr>
              )}
            </tbody>
          </table>
        </div>
      </section>

      <section>
        <div className="flex items-center gap-2 mb-2">
          <h2 className="text-sm font-semibold text-gray-300">Historial de trades simulados ({shown.length})</h2>
          <select
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
            className="bg-gray-900 border border-gray-700 rounded text-xs p-1 text-gray-300"
          >
            <option value="all">todas las configs</option>
            {configs.map((c) => <option key={c} value={c}>{c}</option>)}
          </select>
        </div>
        <div className="overflow-x-auto rounded-lg border border-gray-800 max-h-[28rem] overflow-y-auto">
          <table className="w-full text-xs">
            <thead className="bg-gray-900/60 text-gray-400 sticky top-0">
              <tr>
                <th className="text-left p-2">config</th><th className="text-left p-2">símbolo</th>
                <th className="text-left p-2">dirección</th><th className="text-left p-2">entrada</th>
                <th className="text-left p-2">salida</th><th className="text-right p-2">crédito</th>
                <th className="text-right p-2">P&L</th><th className="text-left p-2">motivo</th>
              </tr>
            </thead>
            <tbody>
              {shown.map((t, i) => {
                const pnl = Number(t.pnl);
                return (
                  <tr key={i} className="border-t border-gray-800/50">
                    <td className="p-1.5 text-gray-500">{t.config}</td>
                    <td className="p-1.5 text-gray-200">{t.symbol}</td>
                    <td className="p-1.5 text-gray-400">{t.direction === 'long' ? 'bull put' : 'bear call'}</td>
                    <td className="p-1.5 text-gray-400">{String(t.entry_date).slice(0, 10)}</td>
                    <td className="p-1.5 text-gray-400">{String(t.exit_date).slice(0, 10)}</td>
                    <td className="p-1.5 text-right text-gray-300">${Number(t.credit).toFixed(0)}</td>
                    <td className={`p-1.5 text-right font-semibold ${pnl > 0 ? 'text-emerald-400' : 'text-red-400'}`}>
                      {pnl >= 0 ? '+' : ''}${pnl.toFixed(2)}
                    </td>
                    <td className="p-1.5 text-gray-500">{t.exit_reason}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </section>
    </Shell>
  );
}
