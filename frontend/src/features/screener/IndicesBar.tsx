import { useEffect, useState } from "react";

import { api } from "@/lib/api";
import { fmtChangePct } from "@/lib/format";
import type { ScreenerRow } from "@/types/api";

// Short display names + a priority order for the major indices.
const SHORT: Record<string, string> = {
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
  const [idx, setIdx] = useState<ScreenerRow[]>([]);

  useEffect(() => {
    const ctrl = new AbortController();
    api
      .screener({ page: 1, page_size: 50, asset_class: "index" }, ctrl.signal)
      .then((p) => setIdx(p.items))
      .catch(() => setIdx([]));
    return () => ctrl.abort();
  }, []);

  if (idx.length === 0) return null;

  const byd = new Map(idx.map((r) => [r.provider_symbol, r]));
  const ordered = [
    ...ORDER.map((s) => byd.get(s)).filter((r): r is ScreenerRow => !!r),
    ...idx.filter((r) => !ORDER.includes(r.provider_symbol)),
  ];

  return (
    <div className="flex flex-wrap items-center gap-2 border-b border-base-600 bg-base-900 px-4 py-2">
      <span className="text-[11px] font-semibold uppercase tracking-wide text-slate-500">
        World Indices
      </span>
      {ordered.map((r) => {
        const chg = r.change_pct;
        const color = chg == null ? "#94a3b8" : chg > 0 ? "#22c55e" : chg < 0 ? "#ef4444" : "#94a3b8";
        return (
          <div
            key={r.provider_symbol}
            className="flex items-center gap-1.5 rounded-md border border-base-600 bg-base-800 px-2.5 py-1"
          >
            <span className="text-xs font-semibold text-slate-200">
              {SHORT[r.provider_symbol] ?? r.name ?? r.symbol}
            </span>
            <span className="num text-xs font-bold text-slate-100">{level(r.price)}</span>
            <span className="num text-[11px] font-semibold" style={{ color }}>
              {fmtChangePct(chg)}
            </span>
          </div>
        );
      })}
    </div>
  );
}
