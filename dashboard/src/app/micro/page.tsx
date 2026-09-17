'use client';

// Micro-Jev live view: every minute-scale decision the Jev model makes,
// its trades, model spend against the hard $2 budget, and the baseline
// policies (random / momentum) on identical state. Data mirrors from the
// bot's sqlite journal to Supabase at the end of every tick.
import { useEffect, useState } from 'react';
import { Shell } from '@/components/Shell';

interface MicroState {
  decisions: Array<{ rid: number; ts: string; symbol: string; have_position: boolean; action: string; p_up: number | string | null; p_exit: number | string | null; note: string | null }>;
  trades: Array<{ id: number; symbol: string; notional: number | string; entry_px: number | string; exit_px: number | string | null; opened_at: string; closed_at: string | null; pnl: number | string | null; exit_reason: string | null }>;
  baselines: Array<{ policy: string; realized: number | string; open_count: number | string; closed_count: number | string }>;
  jev: { realized: number | string; open_count: number | string; closed_count: number | string };
  usage: { spent: number | string; tokens: number | string; calls: number | string };
}

const n = (v: number | string | null | undefined) => (v == null ? 0 : Number(v));

export default function MicroPage() {
  const [s, setS] = useState<MicroState | null>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    const load = () =>
      fetch('/api/micro').then((r) => r.json()).then((d) => (d.error ? setErr(d.error) : setS(d)))
        .catch((e) => setErr(String(e)));
    load();
    const t = setInterval(load, 30_000); // live-ish: refresh every 30s
    return () => clearInterval(t);
  }, []);

  return (
    <Shell>
      <div className="flex items-baseline justify-between mb-3">
        <h1 className="text-lg font-bold">Micro-Jev — minute-scale experiment</h1>
        <a href="/" className="text-xs text-gray-400 underline">← options dashboard</a>
      </div>
      <p className="text-xs text-gray-500 mb-4">
        TypeSafe Jev (typed decision model) answers p(up) / p(exit) every minute on $50
        fractional ETF positions — paper account, hard $2 model budget, code-owned stops.
        Baselines trade the identical state. Auto-refreshes every 30s.
      </p>
      {err && <p className="text-red-400 text-sm">{err}</p>}
      {s && (
        <>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-5">
            <div className="rounded-lg border border-gray-800 bg-gray-900/25 p-3">
              <p className="text-[10px] uppercase tracking-wide text-gray-500">Jev model spend</p>
              <p className="text-xl font-bold">${n(s.usage.spent).toFixed(4)} <span className="text-xs text-gray-500">/ $2.00</span></p>
              <p className="text-[11px] text-gray-500">{n(s.usage.calls)} calls · {n(s.usage.tokens).toLocaleString()} tokens</p>
            </div>
            <div className="rounded-lg border border-gray-800 bg-gray-900/25 p-3">
              <p className="text-[10px] uppercase tracking-wide text-gray-500">Jev book (realized)</p>
              <p className={`text-xl font-bold ${n(s.jev.realized) >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>${n(s.jev.realized).toFixed(2)}</p>
              <p className="text-[11px] text-gray-500">{n(s.jev.open_count)} open · {n(s.jev.closed_count)} closed</p>
            </div>
            {s.baselines.map((b) => (
              <div key={b.policy} className="rounded-lg border border-gray-800 bg-gray-900/25 p-3">
                <p className="text-[10px] uppercase tracking-wide text-gray-500">{b.policy} baseline</p>
                <p className={`text-xl font-bold ${n(b.realized) >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>${n(b.realized).toFixed(2)}</p>
                <p className="text-[11px] text-gray-500">{n(b.open_count)} open · {n(b.closed_count)} closed</p>
              </div>
            ))}
          </div>

          <h2 className="text-sm font-semibold text-gray-300 mb-2">Trades</h2>
          <div className="space-y-1 mb-5">
            {s.trades.length === 0 && <p className="text-sm text-gray-500">No trades yet.</p>}
            {s.trades.map((t) => (
              <div key={t.id} className="rounded border border-gray-800 bg-gray-900/25 px-3 py-1.5 text-xs flex flex-wrap gap-2 items-center">
                <span className="font-semibold">{t.symbol}</span>
                <span className="text-gray-400">${n(t.notional).toFixed(0)} @ {n(t.entry_px).toFixed(2)}</span>
                <span className="text-gray-500">{new Date(t.opened_at).toLocaleTimeString()}</span>
                {t.closed_at ? (
                  <span className={`ml-auto ${n(t.pnl) >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>
                    {t.exit_reason} {n(t.pnl) >= 0 ? '+' : ''}{n(t.pnl).toFixed(2)}$
                  </span>
                ) : (
                  <span className="ml-auto text-amber-400">open</span>
                )}
              </div>
            ))}
          </div>

          <h2 className="text-sm font-semibold text-gray-300 mb-2">Decisions (latest 60)</h2>
          <div className="space-y-1">
            {s.decisions.map((d) => (
              <div key={d.rid} className="rounded border border-gray-800 bg-gray-900/25 px-3 py-1 text-[11px] flex flex-wrap gap-2 items-center">
                <span className="text-gray-500">{new Date(d.ts).toLocaleTimeString()}</span>
                <span className="font-semibold">{d.symbol}</span>
                <span className={d.action === 'enter' ? 'text-emerald-400' : d.action.includes('exit') || d.action === 'hard_stop' || d.action === 'hard_take' ? 'text-amber-400' : d.action === 'jev_error' ? 'text-red-400' : 'text-gray-400'}>{d.action}</span>
                {d.p_up != null && <span className="text-gray-500">p_up {Number(d.p_up).toFixed(2)}</span>}
                {d.p_exit != null && <span className="text-gray-500">p_exit {Number(d.p_exit).toFixed(2)}</span>}
                {d.note && <span className="text-gray-600 truncate max-w-[45%]">{d.note}</span>}
              </div>
            ))}
          </div>
        </>
      )}
    </Shell>
  );
}
