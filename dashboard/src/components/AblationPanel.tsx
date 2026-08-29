// The live ablation: same gate-approved candidates every cycle, three
// selection policies — real book, mechanical rule, matched-rate random.
// Realized and unrealized are shown separately so comparisons stay honest.
interface PolicyRow {
  policy: string;
  realized: number | string;
  unrealized: number | string;
  open_count: number | string;
  closed_count: number | string;
}
interface Ablation {
  llm: {
    realized: number | string;
    unrealized: number | string | null;
    open_count: number | string;
    closed_count: number | string;
  } | null;
  policies: PolicyRow[];
  meta?: {
    n_closed_llm?: number;
    n_cycles?: number;
    abstention_rate?: number | null;
    gate_block_rate?: number | null;
    pretrade_block_rate?: number | null;
    llm_abstain_with_menu?: number;
    reconcile_blocks?: number;
    avg_credit_slippage_pct?: number | null;
    n_slippage_sample?: number;
    abstention_note?: string;
    valid_cycle_coverage_note?: string;
  };
}

function fmt(v: number): string {
  return `${v >= 0 ? '+' : ''}$${v.toFixed(2)}`;
}

function pct(v: number | null | undefined): string {
  if (v == null || Number.isNaN(v)) return 'n/a';
  return `${(v * 100).toFixed(0)}%`;
}

function Cell({
  name,
  realized,
  unrealized,
  note,
}: {
  name: string;
  realized: number;
  unrealized: number | null;
  note: string;
}) {
  const u = unrealized ?? 0;
  const total = realized + u;
  const tone = total > 0 ? 'text-emerald-400' : total < 0 ? 'text-red-400' : 'text-white';
  return (
    <div className="rounded-lg border border-gray-800 bg-gray-900/30 p-3">
      <p className="text-[11px] uppercase tracking-wide text-gray-500">{name}</p>
      <p className={`text-lg font-bold ${tone}`}>{fmt(total)}</p>
      <p className="text-[11px] text-gray-400 mt-0.5">
        realized {fmt(realized)}
        {unrealized != null ? ` · unrealized ${fmt(unrealized)}` : ''}
      </p>
      <p className="text-[11px] text-gray-500 mt-0.5">{note}</p>
    </div>
  );
}

export function AblationPanel({ ablation }: { ablation: Ablation | null }) {
  if (!ablation) return null;
  const byPolicy = Object.fromEntries(ablation.policies.map((p) => [p.policy, p]));
  const shadow = byPolicy['shadow'];
  const random = byPolicy['random'];
  const llm = ablation.llm;
  if (!llm && !shadow && !random) return null;

  const nClosed = Number(llm?.closed_count ?? ablation.meta?.n_closed_llm ?? 0);
  const meta = ablation.meta;

  return (
    <section className="mb-4">
      <h2 className="text-sm font-semibold text-gray-300 mb-2">Live ablation — does the AI add value?</h2>
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-2">
        {llm && (
          <Cell
            name="LLM (real)"
            realized={Number(llm.realized)}
            unrealized={llm.unrealized != null ? Number(llm.unrealized) : 0}
            note={`${llm.open_count} open · ${llm.closed_count} closed · exploratory N=${nClosed}`}
          />
        )}
        {shadow && (
          <Cell
            name="Mechanical rule (virtual)"
            realized={Number(shadow.realized)}
            unrealized={Number(shadow.unrealized)}
            note={`${shadow.open_count} open · ${shadow.closed_count} closed · same menu + exits`}
          />
        )}
        {random && (
          <Cell
            name="Random (virtual)"
            realized={Number(random.realized)}
            unrealized={Number(random.unrealized)}
            note={`${random.open_count} open · ${random.closed_count} closed · matched count + risk`}
          />
        )}
      </div>
      {meta && (
        <div className="mt-2 grid grid-cols-2 sm:grid-cols-4 gap-2 text-[11px] text-gray-400">
          <div className="rounded border border-gray-800 px-2 py-1.5">
            Cycles: <span className="text-gray-200">{meta.n_cycles ?? 0}</span>
          </div>
          <div className="rounded border border-gray-800 px-2 py-1.5">
            Abstention: <span className="text-gray-200">{pct(meta.abstention_rate)}</span>
          </div>
          <div className="rounded border border-gray-800 px-2 py-1.5">
            Gate blocks: <span className="text-gray-200">{pct(meta.gate_block_rate)}</span>
          </div>
          <div className="rounded border border-gray-800 px-2 py-1.5">
            Slippage:{' '}
            <span className="text-gray-200">
              {meta.avg_credit_slippage_pct != null
                ? `${meta.avg_credit_slippage_pct.toFixed(1)}% (n=${meta.n_slippage_sample ?? 0})`
                : 'n/a'}
            </span>
          </div>
        </div>
      )}
      <p className="text-[11px] text-gray-600 mt-1.5">
        All three policies choose among the SAME risk-approved candidates. Virtual books
        fill at estimated mid credit; real fills are execution quality, not part of the
        virtual attribution. One-week N is underpowered — treat as a case study, not proof.
        {meta?.valid_cycle_coverage_note ? ` ${meta.valid_cycle_coverage_note}` : ''}
      </p>
    </section>
  );
}
