// Static — mirrors config.py's OptionsRiskLimits defaults on the deployed
// instance (see the agent repo's config.py / README "Parameter
// optimization pass" for how each value was chosen, incl. the 2026-08-27
// backtest that tried 0.20 delta and reverted to 0.17). Not fetched live
// on purpose: these are deliberately hard-coded, non-negotiable gates the
// LLM decision layer cannot override — showing them as a static list is
// the same claim the code itself makes, not a display of "current mutable
// settings."
const GATES: Array<[string, string]> = [
  ['Target delta (short leg)', '0.17'],
  ['DTE window', '10 – 21 days'],
  ['Max loss per spread', '2% of equity'],
  ['Daily circuit breaker', '-3% P&L'],
  ['Max concurrent spreads', '5'],
  ['Profit target', '50% of credit received'],
  ['Stop', '2× credit received'],
  ['Forced close', 'DTE ≤ 1 or ≤2h before contest end'],
];

export function RiskGatesPanel() {
  return (
    <section className="mb-4">
      <h2 className="text-sm font-semibold text-gray-300 mb-2">Risk gates (code, not the AI)</h2>
      <div className="rounded-lg border border-gray-800 bg-gray-900/20 p-3">
        <dl className="grid grid-cols-1 sm:grid-cols-2 gap-x-4 gap-y-1.5 text-sm">
          {GATES.map(([label, value]) => (
            <div key={label} className="flex justify-between gap-2">
              <dt className="text-gray-500">{label}</dt>
              <dd className="text-gray-200 text-right">{value}</dd>
            </div>
          ))}
        </dl>
        <p className="text-[11px] text-gray-600 mt-2">
          A candidate that fails any of these never reaches the AI decision
          layer.
        </p>
      </div>
    </section>
  );
}
