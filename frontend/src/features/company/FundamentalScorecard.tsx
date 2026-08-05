import type { FundamentalScorecard as Scorecard } from "@/types/company";

// The order the framework defines them in, with the budget each carries. Shown even when a
// category scored nothing, because "0 of 20 on cash flow" is the finding - a category that
// silently vanished would read as though it had never been assessed.
const CATEGORIES: { key: string; label: string }[] = [
  { key: "growth", label: "Growth & Growth Quality" },
  { key: "profitability", label: "Profitability & Margins" },
  { key: "capital_efficiency", label: "Capital Efficiency" },
  { key: "cash_flow", label: "Cash Flow & Earnings Quality" },
  { key: "balance_sheet", label: "Balance Sheet & Solvency" },
  { key: "working_capital", label: "Working Capital & Efficiency" },
];

function tone(pct: number): string {
  if (pct >= 0.8) return "#22c55e";
  if (pct >= 0.6) return "#84cc16";
  if (pct >= 0.4) return "#eab308";
  if (pct >= 0.25) return "#f97316";
  return "#ef4444";
}

export default function FundamentalScorecard({ card }: { card: Scorecard }) {
  if (card.score == null) {
    return (
      <div className="px-4 py-3 text-xs text-slate-500">
        Not scored — the statements on file are too thin to measure. Nothing is estimated in
        their place.
      </div>
    );
  }
  const score = card.score;
  return (
    <div className="px-4 py-3">
      <div className="mb-3 flex flex-wrap items-end gap-4">
        <div className="flex items-baseline gap-1.5">
          <span className="num text-4xl font-black" style={{ color: tone(score / 100) }}>
            {score.toFixed(1)}
          </span>
          <span className="text-sm text-slate-500">/ 100</span>
        </div>
        <div className="flex flex-col gap-0.5">
          <span className="text-sm font-semibold text-slate-200">{card.grade}</span>
          {card.confidence != null && (
            // Not decoration. A 62 built on five periods and half the inputs is a weaker claim
            // than a 62 built on twenty and all of them, and only this says which you have.
            <span className="text-[11px] text-slate-500"
                  title="How much of this score rests on reported data rather than on what happened to be available">
              data confidence {card.confidence.toFixed(0)}%
            </span>
          )}
        </div>
      </div>

      <div className="space-y-1.5">
        {CATEGORIES.map(({ key, label }) => {
          const c = card.categories?.[key];
          if (!c || !c.points) return null;
          const pct = c.points ? c.earned / c.points : 0;
          return (
            <div key={key} className="flex items-center gap-3">
              <span className="w-56 shrink-0 text-[11px] text-slate-400">{label}</span>
              <span className="h-1.5 flex-1 overflow-hidden rounded bg-base-700">
                <span className="block h-full"
                      style={{ width: `${Math.max(0, Math.min(100, pct * 100))}%`,
                               background: tone(pct) }} />
              </span>
              <span className="num w-16 shrink-0 text-right text-[11px] text-slate-300">
                {c.earned.toFixed(1)}/{c.points}
              </span>
            </div>
          );
        })}
      </div>

      {card.flags?.length > 0 && (
        <div className="mt-3 rounded border border-rose-500/30 bg-rose-500/10 px-3 py-2">
          <div className="mb-1 text-[11px] font-semibold uppercase tracking-wide text-rose-300">
            Earnings-quality flags
          </div>
          <ul className="list-inside list-disc text-[11px] text-slate-300">
            {card.flags.map((f) => <li key={f}>{f}</li>)}
          </ul>
        </div>
      )}
    </div>
  );
}
