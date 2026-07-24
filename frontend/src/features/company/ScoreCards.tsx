import { fmtScore, scoreColor } from "@/lib/format";
import type { Row } from "@/types/company";

const COMPONENTS: { key: string; label: string }[] = [
  { key: "fundamental", label: "Fundamental" },
  { key: "technical", label: "Technical" },
  { key: "momentum", label: "Momentum" },
  { key: "quality", label: "Quality" },
  { key: "risk", label: "Risk" },
];

function num(row: Row | null, key: string): number | null {
  const v = row?.[key];
  return typeof v === "number" ? v : null;
}

export default function ScoreCards({ scores }: { scores: Row | null }) {
  const composite = num(scores, "composite");

  return (
    <div className="rounded border border-base-600 bg-base-800 p-4">
      <div className="mb-3 flex items-center justify-between">
        <span className="text-xs font-semibold uppercase tracking-wide text-slate-400">
          Composite Score
        </span>
        <span className="text-3xl font-bold" style={{ color: scoreColor(composite) }}>
          {fmtScore(composite)}
          <span className="text-base text-slate-500">/100</span>
        </span>
      </div>
      <div className="space-y-2">
        {COMPONENTS.map(({ key, label }) => {
          const v = num(scores, key);
          return (
            <div key={key} className="flex items-center gap-3">
              <span className="w-24 text-xs text-slate-400">{label}</span>
              <div className="h-2 flex-1 overflow-hidden rounded bg-base-700">
                <div
                  className="h-full rounded"
                  style={{
                    width: `${v ?? 0}%`,
                    background: scoreColor(v),
                  }}
                />
              </div>
              <span
                className="num w-8 text-right text-xs font-semibold"
                style={{ color: scoreColor(v) }}
              >
                {fmtScore(v)}
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
}
