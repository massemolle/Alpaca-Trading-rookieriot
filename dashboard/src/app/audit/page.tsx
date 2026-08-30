'use client';

// The Audit Log: every decision cycle, in full — the candidates the AI was
// shown, what it selected vs the mechanical rule, its complete reasoning
// with [FACT_ID] citations, and every gate rejection. Below it, the Nightly
// Engineer trail: each evening's self-modification attempt and its verdict
// (KEPT / REVERTED with the failing tests / NO-CHANGE).
import { useEffect, useState } from 'react';
import { Shell } from '@/components/Shell';

interface JournalRow {
  id: number; cycle_id: number; created_at: string;
  decision: string | null; error: string | null;
  candidates: Array<{ ticker: string; direction: string; strength: number; credit_estimate: number; max_loss: number; facts?: Array<{ fact_id: string; value: unknown; source: string; quality: string }> }> | null;
  llm_selected: string[] | null; shadow_selected: string[] | null;
  llm_reasoning: string | null;
  gate_rejections: Array<{ ticker: string; reasons?: string[] }> | null;
  pre_trade_rejections: Array<{ ticker: string; reasons?: string[]; reason?: string }> | null;
}
interface NightlyRow {
  session_date: string; verdict: string; summary: string | null; gate_tail: string | null; created_at: string;
}

function Badge({ text, tone }: { text: string; tone: 'good' | 'bad' | 'mid' }) {
  const cls = tone === 'good' ? 'bg-emerald-950 text-emerald-400'
    : tone === 'bad' ? 'bg-red-950 text-red-400' : 'bg-gray-800 text-gray-400';
  return <span className={`rounded-full px-2 py-0.5 text-[11px] ${cls}`}>{text}</span>;
}

export default function AuditPage() {
  const [journal, setJournal] = useState<JournalRow[]>([]);
  const [nightly, setNightly] = useState<NightlyRow[]>([]);
  const [openId, setOpenId] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetch('/api/audit')
      .then((r) => r.json())
      .then((d) => { setJournal(d.journal ?? []); setNightly(d.nightly ?? []); })
      .catch(() => setError('Failed to load audit data'));
  }, []);

  return (
    <Shell>
      <div className="flex items-baseline justify-between mb-3">
        <h1 className="text-lg font-bold">Audit log</h1>
        <a href="/" className="text-xs text-gray-400 underline">← dashboard</a>
      </div>
      <p className="text-xs text-gray-500 mb-4">
        Every decision cycle in full: the candidate menu the AI was shown, what it
        picked vs the mechanical rule, its complete reasoning with [FACT_ID]
        citations (every number traceable to its source), and each gate rejection.
        Click a row to expand.
      </p>
      {error && <p className="text-red-400 text-sm">{error}</p>}

      <section className="mb-6 space-y-2">
        {journal.map((j) => {
          const nCands = j.candidates?.length ?? 0;
          const picked = j.llm_selected ?? [];
          const shadow = j.shadow_selected ?? [];
          const agree = JSON.stringify([...picked].sort()) === JSON.stringify([...shadow].sort());
          const open = openId === j.id;
          return (
            <div key={j.id} className="rounded-lg border border-gray-800 bg-gray-900/25">
              <button
                onClick={() => setOpenId(open ? null : j.id)}
                className="w-full text-left p-3 flex flex-wrap items-center gap-2 text-sm"
              >
                <span className="text-gray-500 text-xs">{new Date(j.created_at).toLocaleString()}</span>
                <Badge text={j.decision ?? '—'} tone={j.decision === 'opened' ? 'good' : j.decision === 'error' ? 'bad' : 'mid'} />
                <span className="text-gray-300">{nCands} candidate{nCands === 1 ? '' : 's'}</span>
                <span className="text-gray-400">AI: {picked.length ? picked.join(', ') : 'abstained'}</span>
                <span className="text-gray-500 text-xs">rule: {shadow.length ? shadow.join(', ') : 'abstained'}</span>
                {nCands > 0 && <Badge text={agree ? 'AI = rule' : 'AI ≠ rule'} tone={agree ? 'mid' : 'good'} />}
                <span className="ml-auto text-gray-600 text-xs">{open ? '▲' : '▼'}</span>
              </button>
              {open && (
                <div className="px-3 pb-3 text-xs space-y-2">
                  {j.llm_reasoning && (
                    <div>
                      <p className="text-gray-500 uppercase tracking-wide text-[10px] mb-1">AI reasoning (verbatim, [FACT_ID] = cited source)</p>
                      <p className="text-gray-300 whitespace-pre-wrap leading-relaxed">{j.llm_reasoning}</p>
                    </div>
                  )}
                  {(j.candidates?.length ?? 0) > 0 && (
                    <div>
                      <p className="text-gray-500 uppercase tracking-wide text-[10px] mb-1">Candidate menu</p>
                      {j.candidates!.map((c) => (
                        <p key={c.ticker} className="text-gray-400">
                          {c.ticker} {c.direction} · strength {c.strength} · credit ${Number(c.credit_estimate).toFixed(0)} / max loss ${Number(c.max_loss).toFixed(0)}
                        </p>
                      ))}
                    </div>
                  )}
                  {(j.gate_rejections?.length ?? 0) > 0 && (
                    <div>
                      <p className="text-gray-500 uppercase tracking-wide text-[10px] mb-1">Risk-gate rejections (never reached the AI)</p>
                      {j.gate_rejections!.map((g, i) => (
                        <p key={i} className="text-gray-500">{g.ticker}: {(g.reasons ?? []).join('; ')}</p>
                      ))}
                    </div>
                  )}
                  {(j.pre_trade_rejections?.length ?? 0) > 0 && (
                    <div>
                      <p className="text-gray-500 uppercase tracking-wide text-[10px] mb-1">Pre-trade gate (blocked after selection)</p>
                      {j.pre_trade_rejections!.map((g, i) => (
                        <p key={i} className="text-gray-500">{g.ticker}: {(g.reasons ?? (g.reason ? [g.reason] : [])).join('; ')}</p>
                      ))}
                    </div>
                  )}
                  {j.error && <p className="text-red-400">error: {j.error}</p>}
                </div>
              )}
            </div>
          );
        })}
        {journal.length === 0 && !error && <p className="text-sm text-gray-500">No decisions journaled yet.</p>}
      </section>

      <section>
        <h2 className="text-sm font-semibold text-gray-300 mb-2">Nightly engineer — self-modification trail</h2>
        <p className="text-[11px] text-gray-600 mb-2">
          Every evening a Claude (Fable) session may change the trading algorithm.
          Its changes survive only if the full test suite, compilation, and a dry
          trading cycle all pass — otherwise everything is auto-reverted. Both
          outcomes are recorded here, failures included.
        </p>
        <div className="space-y-2">
          {nightly.map((n, i) => (
            <div key={i} className="rounded-lg border border-gray-800 bg-gray-900/25 p-3 text-xs">
              <div className="flex items-center gap-2 mb-1">
                <span className="text-gray-400">{String(n.session_date).slice(0, 10)}</span>
                <Badge text={n.verdict} tone={n.verdict === 'KEPT' ? 'good' : n.verdict === 'REVERTED' ? 'bad' : 'mid'} />
              </div>
              {n.summary && <p className="text-gray-400 whitespace-pre-wrap leading-relaxed max-h-48 overflow-y-auto">{n.summary}</p>}
              {n.verdict === 'REVERTED' && n.gate_tail && (
                <details className="mt-1">
                  <summary className="text-gray-500 cursor-pointer">why it was rejected (gate log)</summary>
                  <pre className="text-gray-500 whitespace-pre-wrap text-[10px] mt-1">{n.gate_tail}</pre>
                </details>
              )}
            </div>
          ))}
          {nightly.length === 0 && <p className="text-sm text-gray-500">No sessions recorded yet — first one runs tonight 21:00 UTC.</p>}
        </div>
      </section>
    </Shell>
  );
}
