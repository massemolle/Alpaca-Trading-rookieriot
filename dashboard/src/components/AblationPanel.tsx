// The live ablation: same gate-approved candidates every cycle, three
// selection policies — Claude (real money), the mechanical rule, and a
// matched-rate random baseline (virtual fills, same sizing, same exits).
// If Claude doesn't beat the rule, this panel says so. That's the point.
interface PolicyRow {
  policy: string;
  realized: number | string;
  unrealized: number | string;
  open_count: number | string;
  closed_count: number | string;
}
interface Ablation {
  llm: { realized: number | string; open_count: number | string; closed_count: number | string } | null;
  policies: PolicyRow[];
}

function fmt(v: number): string {
  return `${v >= 0 ? '+' : ''}$${v.toFixed(2)}`;
}

function Cell({ name, realized, unrealized, note }: { name: string; realized: number; unrealized: number | null; note: string }) {
  const total = realized + (unrealized ?? 0);
  const tone = total > 0 ? 'text-emerald-400' : total < 0 ? 'text-red-400' : 'text-white';
  return (
    <div className="rounded-lg border border-gray-800 bg-gray-900/30 p-3">
      <p className="text-[11px] uppercase tracking-wide text-gray-500">{name}</p>
      <p className={`text-lg font-bold ${tone}`}>{fmt(total)}</p>
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

  return (
    <section className="mb-4">
      <h2 className="text-sm font-semibold text-gray-300 mb-2">Live ablation — does the AI add value?</h2>
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-2">
        {llm && (
          <Cell
            name="Claude (real)"
            realized={Number(llm.realized)}
            unrealized={null}
            note={`${llm.open_count} open · ${llm.closed_count} closed · realized P&L; open risk lives in the equity curve`}
          />
        )}
        {shadow && (
          <Cell
            name="Mechanical rule (virtual)"
            realized={Number(shadow.realized)}
            unrealized={Number(shadow.unrealized)}
            note={`${shadow.open_count} open · ${shadow.closed_count} closed · same candidates, same exits`}
          />
        )}
        {random && (
          <Cell
            name="Random (virtual)"
            realized={Number(random.realized)}
            unrealized={Number(random.unrealized)}
            note={`${random.open_count} open · ${random.closed_count} closed · same trade count as the AI`}
          />
        )}
      </div>
      <p className="text-[11px] text-gray-600 mt-1.5">
        Every cycle, all three policies choose among the SAME risk-gate-approved
        candidates. Virtual books fill at the estimated credit and close by the same
        rules. If the AI doesn't beat the rule, this panel will show it.
      </p>
    </section>
  );
}
