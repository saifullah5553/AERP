import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { api, type ModelPortfolio, type PortfolioHolding } from "@/lib/api";
import { fmtNumber, fmtQuarterEnd } from "@/lib/format";

const MARKETS: { key: string; label: string }[] = [
  { key: "all", label: "All Markets" },
  { key: "psx", label: "Pakistan" },
  { key: "us", label: "US" },
  { key: "india", label: "India" },
  { key: "australia", label: "Australia" },
  { key: "gcc", label: "Saudi (Tadawul)" },
  { key: "dfm", label: "Dubai (DFM)" },
];

function pctColor(v: number | null | undefined): string {
  if (v == null) return "#94a3b8";
  return v > 0 ? "#22c55e" : v < 0 ? "#ef4444" : "#94a3b8";
}

function Holdings({
  region, holdings, summary,
}: {
  region: string;
  holdings: PortfolioHolding[];
  summary?: { holdings: number; avg_return_pct: number; winners: number };
}) {
  if (!holdings?.length) return null;
  const label = MARKETS.find((m) => m.key === region)?.label ?? region.toUpperCase();
  const weight = 100 / holdings.length;
  // The newest reported period behind this market's rankings - so it's explicit that the
  // scores reflect, say, results to 31-03-2026 rather than anything more recent.
  const latestResults = holdings
    .map((h) => h.results_through)
    .filter((d): d is string => !!d)
    .sort()
    .pop();

  return (
    <div className="mb-6">
      <div className="mb-2 flex flex-wrap items-baseline gap-3 px-1">
        <h2 className="text-sm font-bold uppercase tracking-wide text-slate-200">{label}</h2>
        <span className="text-xs text-slate-500">
          {holdings.length} holdings · equal weight ({weight.toFixed(1)}% each)
        </span>
        {latestResults && (
          <span className="rounded bg-base-700 px-2 py-0.5 text-[11px] text-slate-400"
                title="Newest set of reported results behind these rankings">
            results to {latestResults}
          </span>
        )}
        {summary && (
          <span className="text-xs font-semibold" style={{ color: pctColor(summary.avg_return_pct) }}>
            {summary.avg_return_pct > 0 ? "+" : ""}{summary.avg_return_pct}% avg ·{" "}
            {summary.winners}/{summary.holdings} winners
          </span>
        )}
      </div>
      <div className="overflow-x-auto rounded-lg border border-base-600">
        <table className="w-full text-sm">
          <thead className="bg-base-800 text-[10px] uppercase tracking-wide text-slate-400">
            <tr className="border-b border-base-600">
              <th className="px-3 py-2 text-left">#</th>
              <th className="px-3 py-2 text-left">Ticker</th>
              <th className="px-3 py-2 text-left">Company</th>
              <th className="px-3 py-2 text-left">Sector</th>
              <th className="px-3 py-2 text-right">Quality</th>
              <th className="px-3 py-2 text-right"
                  title="The quarter's results this pick was made on">Bought On Results</th>
              <th className="px-3 py-2 text-right">Buy Date</th>
              <th className="px-3 py-2 text-right">Buy Price</th>
              <th className="px-3 py-2 text-right">Price</th>
              <th className="px-3 py-2 text-right">Return %</th>
            </tr>
          </thead>
          <tbody>
            {holdings.map((h, i) => (
              <tr key={h.provider_symbol} className="border-b border-base-700/40 hover:bg-base-700/40">
                <td className="px-3 py-1.5 text-slate-500">{i + 1}</td>
                <td className="px-3 py-1.5">
                  <Link to={`/company/${encodeURIComponent(h.provider_symbol)}`}
                        className="font-semibold text-accent">
                    {h.symbol}
                  </Link>
                </td>
                <td className="px-3 py-1.5 text-slate-300">
                  <span className="block max-w-[220px] truncate" title={h.name ?? ""}>
                    {h.name ?? "—"}
                  </span>
                </td>
                <td className="px-3 py-1.5 text-xs text-slate-400">{h.sector ?? "—"}</td>
                <td className="num px-3 py-1.5 text-right font-semibold text-slate-200">
                  {h.quality_score?.toFixed(1) ?? "—"}
                  {h.quality_grade && (
                    <span className="ml-1.5 text-[10px] font-normal text-slate-500">
                      {h.quality_grade}
                    </span>
                  )}
                </td>
                <td className="num px-3 py-1.5 text-right text-[11px] text-slate-400"
                    title={h.results_through ?? ""}>
                  {/* The quarter whose reported results put this name in the top scorers -
                      the basis for the purchase, not the day it was bought. */}
                  {fmtQuarterEnd(h.results_through)}
                </td>
                <td className="num px-3 py-1.5 text-right text-[11px] text-slate-400">
                  {h.entry_date}
                </td>
                <td className="num px-3 py-1.5 text-right text-slate-400"
                    title={h.entry_price_nominal
                      ? `restated for a split; ${h.entry_price_nominal} was paid`
                      : ""}>
                  {fmtNumber(h.entry_price)}
                  {h.entry_price_nominal != null && (
                    <span className="ml-1 text-[10px] text-amber-400">adj</span>
                  )}
                </td>
                <td className="num px-3 py-1.5 text-right text-slate-300">
                  {fmtNumber(h.price ?? null)}
                </td>
                <td className="num px-3 py-1.5 text-right font-semibold"
                    style={{ color: pctColor(h.return_pct) }}>
                  {h.return_pct == null ? "—"
                    : `${h.return_pct > 0 ? "+" : ""}${h.return_pct}%`}
                </td>

              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

// Model Portfolio: persisted holdings that rebalance once a quarter as results land — new top
// scorers are added, names that fall out of the ranking are dropped. Entry prices are kept so
// the portfolio carries a real track record rather than just today's ranking.
export default function ModelPortfolioPage() {
  const [pf, setPf] = useState<ModelPortfolio | null>(null);
  const [market, setMarket] = useState("all");
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const ctrl = new AbortController();
    api.modelPortfolio(ctrl.signal)
      .then(setPf)
      .finally(() => setLoading(false));
    return () => ctrl.abort();
  }, []);

  const holdings = pf?.holdings ?? {};
  const regions = market === "all" ? Object.keys(holdings) : [market];
  // The WHOLE history, newest first. It was capped at the last twelve, which quietly hid
  // every earlier rebalance - and the point of keeping a record is being able to look back at
  // it. Grouped by rebalance date so each quarter's moves read together.
  const recent = (pf?.changes ?? [])
    .filter((c) => market === "all" || c.region === market)
    .slice()
    .reverse();

  return (
    <div className="flex h-full flex-col bg-base-900 text-slate-200">
      <header className="flex flex-wrap items-center gap-3 border-b border-base-600 bg-base-900 px-5 py-3">
        <Link to="/" className="text-sm text-slate-400 hover:text-accent">← Dashboard</Link>
        <span className="text-lg font-bold text-slate-100">Model Portfolio</span>
        {pf?.last_rebalance_quarter && (
          <span className="rounded bg-base-700 px-2 py-0.5 text-xs text-slate-400">
            rebalanced {pf.last_rebalance_quarter}
          </span>
        )}
        <div className="ml-auto flex flex-wrap gap-1.5">
          {MARKETS.map((m) => (
            <button
              key={m.key}
              onClick={() => setMarket(m.key)}
              className={`rounded-full border px-3 py-1 text-xs font-semibold transition-colors ${
                market === m.key
                  ? "border-accent bg-accent/20 text-accent"
                  : "border-base-500 bg-base-700 text-slate-300 hover:bg-base-600"
              }`}
            >
              {m.label}
            </button>
          ))}
        </div>
      </header>

      <div className="mx-auto w-full max-w-6xl px-4 pt-3">
        <div className="rounded-lg border border-accent/30 bg-accent/10 px-3 py-2 text-[11px] text-slate-300">
          Holds the highest <b>fundamental quality</b> names, rebalanced once a quarter as
          results land: new top scorers are added, names that fall out are dropped. Pakistan
          holds 20, other markets 15, equal weight.
          {" "}
          <b>Each holding is dated to the rebalance its results imply</b>, not to the day the
          portfolio was built — Mar-26 results are acted on at the end of May, two months later,
          because nobody knew them in April. Returns therefore measure <i>the rule</i> from that
          date, not a position anyone held: this portfolio was first built on 2 Aug 2026.
          Research output, not investment advice.
        </div>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto p-4">
        {loading ? (
          <div className="p-8 text-center text-sm text-slate-500">Loading…</div>
        ) : regions.length === 0 ? (
          <div className="p-8 text-center text-sm text-slate-500">
            The portfolio builds on the next daily refresh.
          </div>
        ) : (
          <>
            {regions.map((r) => (
              <Holdings key={r} region={r} holdings={holdings[r] ?? []}
                        summary={pf?.summary?.[r]} />
            ))}

            {recent.length > 0 && (
              <div className="mt-2">
                <h2 className="mb-2 px-1 text-sm font-bold uppercase tracking-wide text-slate-200">
                  Additions &amp; Deletions
                  <span className="ml-2 font-normal normal-case text-slate-500">
                    {recent.length} recorded
                  </span>
                </h2>
                <div className="max-h-[28rem] divide-y divide-base-700/50 overflow-y-auto rounded-lg border border-base-600">
                  {recent.map((c, i) => (
                    <div key={i} className="flex items-center justify-between gap-3 px-3 py-2 text-sm">
                      <div className="flex items-center gap-2">
                        <span className="rounded px-2 py-0.5 text-[11px] font-bold"
                              style={{
                                background: c.action === "add"
                                  ? "rgba(34,197,94,0.16)" : "rgba(239,68,68,0.16)",
                                color: c.action === "add" ? "#22c55e" : "#ef4444",
                              }}>
                          {c.action === "add" ? "ADDED" : "DROPPED"}
                        </span>
                        <span className="font-semibold text-slate-200">{c.symbol}</span>
                        <span className="text-xs uppercase text-slate-500">{c.region}</span>
                        <span className="text-xs text-slate-400">{c.reason}</span>
                      </div>
                      <div className="flex shrink-0 items-center gap-3 text-xs text-slate-500">
                        {c.return_pct != null && (
                          <span className="font-semibold" style={{ color: pctColor(c.return_pct) }}>
                            {c.return_pct > 0 ? "+" : ""}{c.return_pct}%
                          </span>
                        )}
                        <span className="num" title={c.date}>{fmtQuarterEnd(c.date)}</span>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </>
        )}
      </div>
    </div>
  );
}
