import type { FundamentalScorecard as Scorecard } from "@/types/company";

// The six groups of the fifteen-metric matrix, in the order the specification lists them.
//
// These keys must match what the engine publishes. They did not: the list here named six
// categories the adaptive engine has never produced ("profitability", "capital_efficiency",
// "balance_sheet"), and the row below required a `points` field the engine calls
// `applicable_max`. Between them, EVERY category bar was skipped - the breakdown had been
// invisible on every company page while looking like a component that worked.
const CATEGORIES: { key: string; label: string }[] = [
  { key: "growth", label: "Growth" },
  { key: "margins", label: "Margins vs Industry" },
  { key: "leverage", label: "Leverage & Coverage" },
  { key: "returns", label: "Returns on Capital" },
  { key: "liquidity", label: "Liquidity" },
  { key: "cash_flow", label: "Cash Flow" },
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
          {card.applicable_count != null && card.metric_total != null && (
            <span className="text-[11px] text-slate-500">
              scored on {card.scored_count ?? card.applicable_count} of {card.metric_total}
              {card.applicable_count < card.metric_total
                ? ` — ${card.metric_total - card.applicable_count} not applicable to a ${
                    card.model ?? "business of this type"}`
                : ""}
            </span>
          )}
          {card.classification && (
            <span className="text-[11px] text-slate-400">{card.classification}</span>
          )}
        </div>
      </div>

      <div className="space-y-1.5">
        {CATEGORIES.map(({ key, label }) => {
          const c = card.categories?.[key];
          if (!c) return null;
          const max = c.applicable_max ?? 0;
          // A category every one of whose metrics is N/A for this business model is reported
          // as such, not dropped. "N/A for a bank" and "scored zero" are opposite findings and
          // a blank row would let the reader guess wrong.
          if (!max) {
            return (
              <div key={key} className="flex items-center gap-3">
                <span className="w-56 shrink-0 text-[11px] text-slate-400">{label}</span>
                <span className="flex-1 text-[11px] text-slate-600">
                  not applicable to this business model
                </span>
              </div>
            );
          }
          const pct = c.earned / max;
          return (
            <div key={key} className="flex items-center gap-3">
              <span className="w-56 shrink-0 text-[11px] text-slate-400">{label}</span>
              <span className="h-1.5 flex-1 overflow-hidden rounded bg-base-700">
                <span className="block h-full"
                      style={{ width: `${Math.max(0, Math.min(100, pct * 100))}%`,
                               background: tone(pct) }} />
              </span>
              <span className="num w-16 shrink-0 text-right text-[11px] text-slate-300">
                {c.earned.toFixed(1)}/{max.toFixed(1)}
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
