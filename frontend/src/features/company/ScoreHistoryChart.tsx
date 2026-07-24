import type { ScorePoint } from "@/types/company";

// A dependency-free inline-SVG line chart of the composite score over time.
export default function ScoreHistoryChart({ history }: { history: ScorePoint[] }) {
  const points = history
    .filter((p) => p.composite !== null)
    .map((p) => ({ date: p.as_of, value: p.composite as number }));

  if (points.length < 2) {
    return (
      <div className="rounded border border-base-600 bg-base-800 p-4 text-sm text-slate-500">
        Not enough score history yet to chart.
      </div>
    );
  }

  const W = 100;
  const H = 40;
  const values = points.map((p) => p.value);
  const min = Math.min(...values, 0);
  const max = Math.max(...values, 100);
  const span = max - min || 1;

  const coords = points.map((p, i) => {
    const x = (i / (points.length - 1)) * W;
    const y = H - ((p.value - min) / span) * H;
    return `${x.toFixed(2)},${y.toFixed(2)}`;
  });
  const last = points[points.length - 1].value;

  return (
    <div className="rounded border border-base-600 bg-base-800 p-4">
      <div className="mb-2 flex items-center justify-between">
        <span className="text-xs font-semibold uppercase tracking-wide text-slate-400">
          Composite History
        </span>
        <span className="num text-sm text-slate-300">{last.toFixed(0)}</span>
      </div>
      <svg viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" className="h-24 w-full">
        <polyline
          points={coords.join(" ")}
          fill="none"
          stroke="#38bdf8"
          strokeWidth={1.5}
          vectorEffect="non-scaling-stroke"
        />
      </svg>
      <div className="mt-1 flex justify-between text-[10px] text-slate-500">
        <span>{points[0].date}</span>
        <span>{points[points.length - 1].date}</span>
      </div>
    </div>
  );
}
