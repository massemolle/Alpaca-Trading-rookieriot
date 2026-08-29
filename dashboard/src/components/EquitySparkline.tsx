'use client';

// A plain inline SVG sparkline — no charting library dependency needed for
// a single line over ≤5 trading days of points. Now with a second, dashed
// series: SPY buy-and-hold rebased to the account's starting equity, so the
// gap between the lines IS the agent's excess return ("skill vs market").
interface Point {
  equity: number | string;
  spy_price?: number | string | null;
  snapshot_at: string;
}

export function EquitySparkline({ points }: { points: Point[] }) {
  if (points.length < 2) {
    return <div className="text-sm text-gray-500">Not enough data yet for a curve.</div>;
  }
  // Postgres numerics arrive as strings through the API — coerce before math.
  const equities = points.map((p) => Number(p.equity));

  const firstSpyIdx = points.findIndex((p) => p.spy_price != null && Number(p.spy_price) > 0);
  const spySeries: (number | null)[] = points.map((p, i) => {
    if (firstSpyIdx === -1 || i < firstSpyIdx || p.spy_price == null) return null;
    const base = Number(points[firstSpyIdx].spy_price);
    return (Number(p.spy_price) / base) * equities[firstSpyIdx];
  });

  const values = equities.concat(spySeries.filter((v): v is number => v !== null));
  const min = Math.min(...values);
  const max = Math.max(...values);
  const range = max - min || 1;
  const width = 600;
  const height = 120;
  const step = width / (points.length - 1);
  const y = (v: number) => height - ((v - min) / range) * height;

  const path = equities
    .map((v, i) => `${i === 0 ? 'M' : 'L'}${(i * step).toFixed(1)},${y(v).toFixed(1)}`)
    .join(' ');

  const spyPath = spySeries
    .map((v, i) => (v === null ? null : `${(i * step).toFixed(1)},${y(v).toFixed(1)}`))
    .filter((s): s is string => s !== null)
    .map((coords, j) => `${j === 0 ? 'M' : 'L'}${coords}`)
    .join(' ');

  const up = equities[equities.length - 1] >= equities[0];

  return (
    <div>
      <svg viewBox={`0 0 ${width} ${height}`} className="w-full h-24" preserveAspectRatio="none">
        {spyPath && (
          <path d={spyPath} fill="none" stroke="#6b7280" strokeWidth={1.5} strokeDasharray="4 3" />
        )}
        <path d={path} fill="none" stroke={up ? '#34d399' : '#f87171'} strokeWidth={2} />
      </svg>
      {spyPath && (
        <p className="text-[11px] text-gray-600 mt-1">
          <span className="text-gray-400">━ account</span>
          {' · '}
          <span>┄ SPY (same starting investment)</span>
        </p>
      )}
    </div>
  );
}
