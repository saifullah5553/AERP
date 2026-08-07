/**
 * The fundamental score for every stored TTM period, broken into its six categories.
 *
 * The score history was only ever a line on a chart. A line answers "is this getting better",
 * which is worth knowing, but not "better at WHAT" - and 62 -> 71 can be cash flow recovering,
 * leverage coming down or a one-off in growth, which are three different companies.
 *
 * Newest first, because the question asked of this table is almost always about the latest
 * period and the one before it.
 */

interface Point {
  date: string;
  score: number;
  cats?: Record<string, number> | null;
  confidence?: number | null;
}

const CATEGORIES: { key: string; label: string; outOf: number }[] = [
  { key: "growth", label: "Growth", outOf: 20 },
  { key: "profitability", label: "Profit", outOf: 20 },
  { key: "cash_flow", label: "Cash", outOf: 25 },
  { key: "balance_sheet", label: "Bal Sheet", outOf: 15 },
  { key: "liquidity", label: "Liquidity", outOf: 10 },
  { key: "working_capital", label: "Wkg Cap", outOf: 10 },
];

/** TTM label: "Mar 26" is the twelve months ENDED 31 Mar 26, not the Jan-Mar quarter. */
function ttmLabel(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  const m = ["Mar", "Jun", "Sep", "Dec"][Math.floor(d.getUTCMonth() / 3)];
  return `${m} ${String(d.getUTCFullYear()).slice(2)}`;
}

function heat(v: number | null | undefined, outOf: number): string | undefined {
  if (v == null) return undefined;
  const hue = Math.max(0, Math.min(120, (v / outOf) * 120));
  return `hsla(${hue}, 70%, 45%, 0.22)`;
}

export default function QualityHistoryTable({ history }: { history: Point[] | null | undefined }) {
  const points = (history ?? []).filter((p) => p && typeof p.score === "number");
  if (points.length === 0) return null;

  // Stored oldest-first; newest-first is what gets read.
  const rows = [...points].reverse();
  const withCats = rows.some((r) => r.cats && Object.keys(r.cats).length > 0);

  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[640px] text-xs">
        <thead>
          <tr className="border-b border-base-500 text-left text-[10px] uppercase tracking-wide text-slate-400">
            <th className="px-2 py-1.5 font-semibold">TTM ended</th>
            <th className="px-2 py-1.5 text-right font-semibold">Score /100</th>
            <th className="px-2 py-1.5 text-right font-semibold">Chg</th>
            {withCats &&
              CATEGORIES.map((c) => (
                <th key={c.key} className="px-2 py-1.5 text-right font-semibold">
                  {c.label} /{c.outOf}
                </th>
              ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((p, i) => {
            // Against the period BEFORE it chronologically, which is the next row down.
            const prev = rows[i + 1];
            const chg = prev ? p.score - prev.score : null;
            return (
              <tr key={p.date} className="border-b border-base-700/40">
                <td className="px-2 py-1 text-slate-300">{ttmLabel(p.date)}</td>
                <td
                  className="px-2 py-1 text-right font-semibold tabular-nums"
                  style={{ backgroundColor: heat(p.score, 100) }}
                >
                  {p.score.toFixed(1)}
                </td>
                <td
                  className="px-2 py-1 text-right tabular-nums"
                  style={{ color: chg == null ? undefined : chg > 0 ? "#22c55e" : chg < 0 ? "#ef4444" : undefined }}
                >
                  {chg == null ? "—" : `${chg > 0 ? "+" : ""}${chg.toFixed(1)}`}
                </td>
                {withCats &&
                  CATEGORIES.map((c) => {
                    const v = p.cats?.[c.key];
                    return (
                      <td
                        key={c.key}
                        className="px-2 py-1 text-right tabular-nums text-slate-300"
                        style={{ backgroundColor: heat(v, c.outOf) }}
                      >
                        {v == null ? "—" : v.toFixed(1)}
                      </td>
                    );
                  })}
              </tr>
            );
          })}
        </tbody>
      </table>
      <p className="mt-2 text-[10px] text-slate-500">
        Each row is a full trailing twelve months, scored on only the statements available at
        that period end — never on later ones. A blank category is one the statements could not
        support, or that does not apply to this business; its weight returns to the others
        rather than being scored as a failure.
      </p>
    </div>
  );
}
