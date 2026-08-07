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
  /** Points AVAILABLE per category for that period - not always the standard budget. */
  cats_max?: Record<string, number> | null;
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
  if (v == null || outOf <= 0) return undefined;
  const hue = Math.max(0, Math.min(120, (v / outOf) * 120));
  return `hsla(${hue}, 70%, 45%, 0.22)`;
}

/**
 * A category the period could not be marked on, as opposed to one it scored nothing in.
 *
 * A bank has no cash-conversion cycle, so working capital is skipped and the total renormalises
 * over the 90 points that did apply. Printing "0.0" for that read as a company scoring nothing,
 * and made the six marks fail to add up to the published score for one company in five.
 */
function isSkipped(p: Point, key: string): boolean {
  const max = p.cats_max?.[key];
  return max != null && max <= 0;
}

/** Marks earned, and the points actually in play, for one period. */
function totals(p: Point): { earned: number; available: number } {
  let earned = 0;
  let available = 0;
  for (const c of CATEGORIES) {
    if (isSkipped(p, c.key)) continue;
    const v = p.cats?.[c.key];
    if (v == null) continue;
    earned += v;
    available += p.cats_max?.[c.key] ?? c.outOf;
  }
  return { earned, available };
}

export default function QualityHistoryTable({ history }: { history: Point[] | null | undefined }) {
  const points = (history ?? []).filter((p) => p && typeof p.score === "number");
  if (points.length === 0) return null;

  // Stored oldest-first; newest-first is what gets read.
  const rows = [...points].reverse();
  const withCats = rows.some((r) => r.cats && Object.keys(r.cats).length > 0);
  const anySkipped = rows.some((r) => CATEGORIES.some((c) => isSkipped(r, c.key)));

  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[760px] text-xs">
        <thead>
          <tr className="border-b border-base-500 text-left text-[10px] uppercase tracking-wide text-slate-400">
            <th className="px-2 py-1.5 font-semibold">TTM ended</th>
            {withCats &&
              CATEGORIES.map((c) => (
                <th key={c.key} className="px-2 py-1.5 text-right font-semibold">
                  {c.label} /{c.outOf}
                </th>
              ))}
            {withCats && (
              <th className="px-2 py-1.5 text-right font-semibold" title="The six marks added up">
                Total
              </th>
            )}
            <th className="px-2 py-1.5 text-right font-semibold">Score /100</th>
            <th className="px-2 py-1.5 text-right font-semibold">Chg</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((p, i) => {
            // Against the period BEFORE it chronologically, which is the next row down.
            const prev = rows[i + 1];
            const chg = prev ? p.score - prev.score : null;
            const t = totals(p);
            return (
              <tr key={p.date} className="border-b border-base-700/40">
                <td className="px-2 py-1 text-slate-300">{ttmLabel(p.date)}</td>
                {withCats &&
                  CATEGORIES.map((c) => {
                    if (isSkipped(p, c.key)) {
                      return (
                        <td
                          key={c.key}
                          className="px-2 py-1 text-right text-slate-600"
                          title="Not applicable to this business - the score is marked out of the rest"
                        >
                          n/a
                        </td>
                      );
                    }
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
                {withCats && (
                  <td
                    className="px-2 py-1 text-right tabular-nums font-semibold text-slate-200"
                    title={`The six marks add to ${t.earned.toFixed(1)} out of the ${t.available.toFixed(0)} points that applied`}
                  >
                    {t.earned.toFixed(1)}
                    <span className="text-slate-500"> /{t.available.toFixed(0)}</span>
                  </td>
                )}
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
              </tr>
            );
          })}
        </tbody>
      </table>
      <p className="mt-2 text-[10px] text-slate-500">
        Each row is a full trailing twelve months, scored on only the statements available at
        that period end — never on later ones.{" "}
        {anySkipped ? (
          <>
            <b>Score /100</b> is <b>Total</b> rescaled: where a category does not apply to this
            business it is marked <i>n/a</i> and the total is taken out of the points that did
            apply, so the two columns differ. A bank has no cash-conversion cycle, and scoring
            it zero for lacking one would be a penalty for being a bank.
          </>
        ) : (
          <>
            <b>Score /100</b> equals <b>Total</b> here: every category applied to this business,
            so the marks are out of the full hundred.
          </>
        )}
      </p>
    </div>
  );
}
