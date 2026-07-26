import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";

import { api } from "@/lib/api";
import { fmtChangePct, fmtNumber } from "@/lib/format";
import type { MarketRegion, SwingRow } from "@/types/api";

const REGIONS: { value: MarketRegion | "all"; label: string }[] = [
  { value: "all", label: "All Markets" },
  { value: "psx", label: "Pakistan" },
  { value: "us", label: "US" },
  { value: "india", label: "India" },
  { value: "gcc", label: "GCC" },
  { value: "australia", label: "Australia" },
];

function tone(v: number | null): string {
  if (v == null) return "#64748b";
  return v >= 60 ? "#22c55e" : v >= 45 ? "#eab308" : "#f87171";
}

function Bar({ v }: { v: number | null }) {
  return (
    <span className="flex items-center justify-end gap-1.5">
      <span className="num text-xs" style={{ color: tone(v) }}>{v == null ? "—" : Math.round(v)}</span>
      <span className="hidden h-1.5 w-10 overflow-hidden rounded bg-base-700 sm:block">
        <span className="block h-full" style={{ width: `${v ?? 0}%`, background: tone(v) }} />
      </span>
    </span>
  );
}

// Swing / positional Opportunity Scanner (Feature 3): ranks quality names whose
// fundamentals, sector strength, live macro regime, cost trends and technical setup
// line up. A research ranking — not a buy/sell signal.
export default function SwingPage() {
  const [rows, setRows] = useState<SwingRow[] | null>(null);
  const [region, setRegion] = useState<MarketRegion | "all">("all");
  const [minScore, setMinScore] = useState(0);
  const navigate = useNavigate();

  useEffect(() => {
    const ctrl = new AbortController();
    api.swing(ctrl.signal).then(setRows).catch(() => setRows([]));
    return () => ctrl.abort();
  }, []);

  const filtered = useMemo(() => {
    let list = rows ?? [];
    if (region !== "all") list = list.filter((r) => r.region === region);
    if (minScore > 0) list = list.filter((r) => r.swing_score >= minScore);
    return list.slice(0, 200);
  }, [rows, region, minScore]);

  return (
    <div className="flex h-full flex-col bg-base-900 text-slate-200">
      <header className="flex flex-wrap items-center justify-between gap-3 border-b border-base-600 bg-base-900 px-4 py-2.5">
        <div className="flex items-baseline gap-3">
          <Link to="/" className="text-sm text-slate-400 hover:text-accent">← Screener</Link>
          <span className="text-lg font-bold tracking-tight text-accent">Swing Opportunity Scanner</span>
          <span className="hidden text-xs text-slate-500 md:inline">
            fundamentals + sector + macro regime + cost trend + technical setup · research ranking, not a signal
          </span>
        </div>
        <label className="flex items-center gap-2 text-xs text-slate-400">
          Min score {minScore}
          <input type="range" min={0} max={90} value={minScore}
                 onChange={(e) => setMinScore(Number(e.target.value))} className="w-32 accent-accent" />
        </label>
      </header>

      <div className="flex flex-wrap gap-1 border-b border-base-600 bg-base-800 px-4 py-2">
        {REGIONS.map((r) => (
          <button key={r.value} onClick={() => setRegion(r.value)}
            className={`rounded px-3 py-1.5 text-sm font-medium ${
              region === r.value ? "bg-accent-muted text-white" : "bg-base-700 text-slate-300 hover:bg-base-600"
            }`}>
            {r.label}
          </button>
        ))}
      </div>

      <div className="flex-1 overflow-auto p-4">
        {rows == null ? (
          <div className="p-8 text-center text-sm text-slate-500">Loading opportunities…</div>
        ) : filtered.length === 0 ? (
          <div className="p-8 text-center text-sm text-slate-500">No opportunities match the filter.</div>
        ) : (
          <table className="w-full border-collapse text-sm">
            <thead>
              <tr className="border-b border-base-600 text-left text-[11px] uppercase tracking-wide text-slate-500">
                <th className="py-2 pr-3">#</th>
                <th className="py-2 pr-3">Ticker</th>
                <th className="py-2 pr-3">Company</th>
                <th className="py-2 pr-3">Sector</th>
                <th className="num py-2 pr-3 text-right">Swing</th>
                <th className="num py-2 pr-3 text-right">Fund 40%</th>
                <th className="num py-2 pr-3 text-right">Catalyst 25%</th>
                <th className="num py-2 pr-3 text-right">Tech 25%</th>
                <th className="num py-2 pr-3 text-right">Risk 10%</th>
                <th className="num py-2 pr-3 text-right">Price</th>
                <th className="num py-2 pr-3 text-right">Chg%</th>
              </tr>
            </thead>
            <tbody>
              {filtered.map((r, i) => (
                <tr
                  key={r.provider_symbol}
                  onClick={() => navigate(`/company/${encodeURIComponent(r.provider_symbol)}`)}
                  className="cursor-pointer border-b border-base-700/40 hover:bg-base-800/60"
                >
                  <td className="num py-2 pr-3 text-slate-500">{i + 1}</td>
                  <td className="py-2 pr-3 font-semibold text-accent">{r.symbol}</td>
                  <td className="max-w-[220px] truncate py-2 pr-3 text-slate-300">{r.name}</td>
                  <td className="max-w-[160px] truncate py-2 pr-3 text-slate-500">{r.sector}</td>
                  <td className="num py-2 pr-3 text-right font-bold" style={{ color: tone(r.swing_score) }}>
                    {Math.round(r.swing_score)}
                  </td>
                  <td className="py-2 pr-3"><Bar v={r.fundamental} /></td>
                  <td className="py-2 pr-3"><Bar v={r.catalyst} /></td>
                  <td className="py-2 pr-3"><Bar v={r.technical} /></td>
                  <td className="py-2 pr-3"><Bar v={r.risk} /></td>
                  <td className="num py-2 pr-3 text-right text-slate-300">{fmtNumber(r.price)}</td>
                  <td className="num py-2 pr-3 text-right"
                      style={{ color: (r.change_pct ?? 0) > 0 ? "#22c55e" : (r.change_pct ?? 0) < 0 ? "#ef4444" : "#94a3b8" }}>
                    {fmtChangePct(r.change_pct)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
