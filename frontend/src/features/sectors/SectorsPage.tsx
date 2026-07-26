import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";

import { api } from "@/lib/api";
import { fmtPercent } from "@/lib/format";
import type { MarketRegion, SectorStat, SectorStatsData } from "@/types/api";

const REGIONS: { value: MarketRegion; label: string }[] = [
  { value: "psx", label: "Pakistan" },
  { value: "us", label: "US" },
  { value: "india", label: "India" },
  { value: "gcc", label: "GCC" },
  { value: "australia", label: "Australia" },
];

const TREND_TONE: Record<string, string> = {
  Strong: "#22c55e", Improving: "#4ade80", Neutral: "#94a3b8", Weak: "#f87171", "—": "#64748b",
};

function scoreTone(v: number | null): string {
  if (v == null) return "#64748b";
  return v >= 60 ? "#22c55e" : v >= 45 ? "#eab308" : "#f87171";
}

// Sector Rotation dashboard (Feature 2): rank sectors within a market by the platform's
// own aggregated scores + breadth trend, so a trader picks strong sectors before stocks.
export default function SectorsPage() {
  const [data, setData] = useState<SectorStatsData | null>(null);
  const [region, setRegion] = useState<MarketRegion>("psx");
  const [strongOnly, setStrongOnly] = useState(false);

  useEffect(() => {
    const ctrl = new AbortController();
    api.sectorStats(ctrl.signal).then(setData).catch(() => setData(null));
    return () => ctrl.abort();
  }, []);

  const rows = useMemo(() => {
    const list = (data?.[region] ?? []) as SectorStat[];
    return strongOnly ? list.filter((s) => s.trend === "Strong" || s.trend === "Improving") : list;
  }, [data, region, strongOnly]);

  return (
    <div className="flex h-full flex-col bg-base-900 text-slate-200">
      <header className="flex flex-wrap items-center justify-between gap-3 border-b border-base-600 bg-base-900 px-4 py-2.5">
        <div className="flex items-baseline gap-3">
          <Link to="/" className="text-sm text-slate-400 hover:text-accent">← Screener</Link>
          <span className="text-lg font-bold tracking-tight text-accent">Sector Rotation</span>
          <span className="text-xs text-slate-500">strong sectors first — pick the sector, then the stock</span>
        </div>
        <label className="flex items-center gap-2 text-xs text-slate-400">
          <input type="checkbox" checked={strongOnly} onChange={(e) => setStrongOnly(e.target.checked)} className="accent-accent" />
          Strong / improving only
        </label>
      </header>

      <div className="flex flex-wrap gap-1 border-b border-base-600 bg-base-800 px-4 py-2">
        {REGIONS.map((r) => (
          <button
            key={r.value}
            onClick={() => setRegion(r.value)}
            className={`rounded px-3 py-1.5 text-sm font-medium ${
              region === r.value ? "bg-accent-muted text-white" : "bg-base-700 text-slate-300 hover:bg-base-600"
            }`}
          >
            {r.label}
          </button>
        ))}
      </div>

      <div className="flex-1 overflow-auto p-4">
        {rows.length === 0 ? (
          <div className="p-8 text-center text-sm text-slate-500">
            No sector data for this market yet.
          </div>
        ) : (
          <table className="w-full border-collapse text-sm">
            <thead>
              <tr className="border-b border-base-600 text-left text-[11px] uppercase tracking-wide text-slate-500">
                <th className="py-2 pr-3">#</th>
                <th className="py-2 pr-3">Sector</th>
                <th className="num py-2 pr-3 text-right">Score</th>
                <th className="py-2 pr-3">Trend</th>
                <th className="num py-2 pr-3 text-right">Momentum</th>
                <th className="num py-2 pr-3 text-right">Fundamental</th>
                <th className="num py-2 pr-3 text-right">ROE</th>
                <th className="num py-2 pr-3 text-right">Net Margin</th>
                <th className="num py-2 pr-3 text-right">Rev Growth</th>
                <th className="num py-2 pr-3 text-right">Names</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((s, i) => (
                <tr key={s.sector} className="border-b border-base-700/40 hover:bg-base-800/60">
                  <td className="num py-2 pr-3 text-slate-500">{i + 1}</td>
                  <td className="py-2 pr-3 font-medium text-slate-200">{s.sector}</td>
                  <td className="num py-2 pr-3 text-right font-semibold" style={{ color: scoreTone(s.score) }}>
                    {Math.round(s.score)}
                  </td>
                  <td className="py-2 pr-3 font-medium" style={{ color: TREND_TONE[s.trend] ?? "#94a3b8" }}>{s.trend}</td>
                  <td className="num py-2 pr-3 text-right" style={{ color: scoreTone(s.momentum) }}>
                    {s.momentum == null ? "—" : Math.round(s.momentum)}
                  </td>
                  <td className="num py-2 pr-3 text-right" style={{ color: scoreTone(s.fundamental) }}>
                    {s.fundamental == null ? "—" : Math.round(s.fundamental)}
                  </td>
                  <td className="num py-2 pr-3 text-right text-slate-300">{fmtPercent(s.medians.roe)}</td>
                  <td className="num py-2 pr-3 text-right text-slate-300">{fmtPercent(s.medians.net_margin)}</td>
                  <td className="num py-2 pr-3 text-right text-slate-300">{fmtPercent(s.medians.revenue_growth)}</td>
                  <td className="num py-2 pr-3 text-right text-slate-500">{s.count}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
