import { useEffect, useState } from "react";

import { api, type ExtraIndex } from "@/lib/api";
import { fmtChangePct } from "@/lib/format";

// Minimal shape shared by Yahoo index rows and the P360 KSE100 extra.
type Idx = { provider_symbol: string; symbol: string; name: string | null; price: number | null; change_pct: number | null };

// Short display names + a priority order for the major indices.
const SHORT: Record<string, string> = {
  KSE100: "KSE 100",
  "^GSPC": "S&P 500", "^IXIC": "NASDAQ", "^DJI": "Dow Jones", "^RUT": "Russell 2000",
  "^NSEI": "NIFTY 50", "^BSESN": "SENSEX", "^TASI.SR": "Tadawul", "^AXJO": "ASX 200",
  "^FTSE": "FTSE 100", "^GDAXI": "DAX", "^N225": "Nikkei 225", "^HSI": "Hang Seng",
};
const ORDER = ["^GSPC", "^IXIC", "^DJI", "^NSEI", "^BSESN", "^TASI.SR", "^AXJO",
  "^FTSE", "^GDAXI", "^N225", "^HSI", "^RUT"];

function level(v: number | null): string {
  return v == null ? "—" : v.toLocaleString(undefined, { maximumFractionDigits: 2 });
}

// A live-ish world-index ticker: current level + day change per major index (chart-v8
// refreshed each snapshot). Replaces the old per-market sentiment strip (which duplicated
// the KPI sentiment bar + the regime cards).
export default function IndicesBar() {
  const [idx, setIdx] = useState<Idx[]>([]);
  const [extra, setExtra] = useState<ExtraIndex[]>([]);

  useEffect(() => {
    const ctrl = new AbortController();
    api
      .screener({ page: 1, page_size: 50, asset_class: "index" }, ctrl.signal)
      .then((p) => setIdx(p.items))
      .catch(() => setIdx([]));
    api.extraIndices(ctrl.signal).then(setExtra).catch(() => setExtra([]));
    return () => ctrl.abort();
  }, []);

  if (idx.length === 0 && extra.length === 0) return null;

  const byd = new Map(idx.map((r) => [r.provider_symbol, r]));
  const yahoo = [
    ...ORDER.map((s) => byd.get(s)).filter((r): r is Idx => !!r),
    ...idx.filter((r) => !ORDER.includes(r.provider_symbol)),
  ];
  // Home market (KSE100 from P360) leads the strip.
  const ordered: Idx[] = [...extra, ...yahoo];

  const chip = (r: Idx, i: number) => {
    const chg = r.change_pct;
    const color = chg == null ? "#94a3b8" : chg > 0 ? "#22c55e" : chg < 0 ? "#ef4444" : "#94a3b8";
    return (
      <span key={`${r.provider_symbol}-${i}`} className="mx-3 inline-flex items-center gap-1.5 whitespace-nowrap">
        <span className="text-xs font-semibold text-slate-300">
          {SHORT[r.provider_symbol] ?? r.name ?? r.symbol}
        </span>
        <span className="num text-xs font-bold text-slate-100">{level(r.price)}</span>
        <span className="num text-[11px] font-semibold" style={{ color }}>{fmtChangePct(chg)}</span>
        <span className="text-slate-700">·</span>
      </span>
    );
  };

  return (
    <div className="flex items-center gap-2 border-b border-base-600 bg-base-900 py-1.5">
      <span className="shrink-0 border-r border-base-600 pl-4 pr-3 text-[11px] font-semibold uppercase tracking-wide text-slate-500">
        World Indices
      </span>
      <div className="relative flex-1 overflow-hidden">
        <div className="marquee-track">
          {[...ordered, ...ordered].map((r, i) => chip(r, i))}
        </div>
      </div>
    </div>
  );
}
