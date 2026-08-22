import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { api, type Mover, type MoversData } from "@/lib/api";
import { fmtSnapshotAge } from "@/lib/format";
import { Th, useSortable } from "@/lib/useSortable";

// A TABLE rather than the card list this used to be. The cards had no column headers, so
// this was the one page with nothing to click: movers arrived in whatever order the backend
// emitted and could not be re-ordered by score, market or name.
function MoverRow({ m, up }: { m: Mover; up: boolean }) {
  const color = up ? "#22c55e" : "#ef4444";
  return (
    <tr className="border-t border-base-700/40 hover:bg-base-700/40">
      <td className="px-3 py-1.5 font-semibold text-accent">
        <Link to={`/company/${encodeURIComponent(m.provider_symbol)}`}>{m.symbol}</Link>
      </td>
      <td className="max-w-[220px] truncate px-3 py-1.5 text-xs text-slate-400" title={m.name ?? ""}>
        {m.name}
      </td>
      <td className="px-3 py-1.5">
        <span className="rounded bg-base-700 px-1 py-0.5 text-[9px] uppercase text-slate-500">
          {m.region}
        </span>
      </td>
      <td className="num px-3 py-1.5 text-right text-slate-400">{m.prev}</td>
      <td className="num px-3 py-1.5 text-right text-slate-300">{m.composite}</td>
      <td className="num px-3 py-1.5 text-right font-bold" style={{ color }}>
        {up ? "+" : ""}{m.delta}
      </td>
    </tr>
  );
}

function Panel({ title, tone, movers, up }: { title: string; tone: string; movers: Mover[]; up: boolean }) {
  const value = useCallback((m: Mover, key: string): unknown => {
    switch (key) {
      case "symbol": return m.symbol;
      case "name": return m.name;
      case "region": return m.region;
      case "prev": return m.prev;
      case "composite": return m.composite;
      case "delta": return m.delta;
      default: return null;
    }
  }, []);
  const { sorted, sort, toggle } = useSortable(movers, value, { key: "delta", dir: "desc" });
  return (
    <div className="flex min-h-0 flex-col overflow-hidden rounded-lg border border-base-600 bg-base-800">
      <div className="flex items-center justify-between border-b border-base-600 px-3 py-2">
        <span className="text-sm font-bold" style={{ color: tone }}>{title}</span>
        <span className="num text-xs text-slate-400">{movers.length}</span>
      </div>
      {movers.length === 0 ? (
        <div className="p-6 text-center text-xs text-slate-500">
          None yet — this fills as composite scores change on refresh.
        </div>
      ) : (
        <div className="overflow-y-auto">
          <table className="w-full text-sm">
            <thead className="sticky top-0 bg-base-800 text-[10px] uppercase tracking-wide text-slate-400">
              <tr>
                <Th sortKey="symbol" sort={sort} onSort={toggle} className="px-3 py-2 text-left">Ticker</Th>
                <Th sortKey="name" sort={sort} onSort={toggle} className="px-3 py-2 text-left">Company</Th>
                <Th sortKey="region" sort={sort} onSort={toggle} className="px-3 py-2 text-left">Market</Th>
                <Th sortKey="prev" sort={sort} onSort={toggle} align="right" className="px-3 py-2 text-right">Was</Th>
                <Th sortKey="composite" sort={sort} onSort={toggle} align="right" className="px-3 py-2 text-right">Now</Th>
                <Th sortKey="delta" sort={sort} onSort={toggle} align="right" className="px-3 py-2 text-right">Change</Th>
              </tr>
            </thead>
            <tbody>
              {sorted.map((m) => <MoverRow key={m.provider_symbol} m={m} up={up} />)}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

// Upgrades/downgrades: stocks whose composite score rose/fell vs the prior refresh
// (rolling 7-day feed). PSX recomputes every refresh; other markets appear once their
// scores recompute.
export default function MoversPage() {
  const [data, setData] = useState<MoversData | null>(null);

  useEffect(() => {
    const ctrl = new AbortController();
    api.movers(ctrl.signal).then(setData).catch(() => setData(null));
    return () => ctrl.abort();
  }, []);

  const ups = data?.upgrades ?? [];
  const downs = data?.downgrades ?? [];

  return (
    <div className="flex h-full flex-col bg-base-900 text-slate-200">
      <header className="flex flex-wrap items-center gap-3 border-b border-base-600 bg-base-900 px-5 py-3">
        <Link to="/" className="text-sm text-slate-400 hover:text-accent">← Dashboard</Link>
        <span className="text-lg font-bold text-slate-100">Score Movers</span>
        <span className="rounded bg-base-700 px-2 py-0.5 text-xs text-slate-400">
          {ups.length} up · {downs.length} down
        </span>
        {data?.generated_at && (
          <span className="ml-auto text-[11px] text-slate-500">Updated {fmtSnapshotAge(data.generated_at)}</span>
        )}
      </header>
      <div className="grid min-h-0 flex-1 gap-4 overflow-hidden p-4 md:grid-cols-2">
        <Panel title="▲ Upgrades" tone="#22c55e" movers={ups} up />
        <Panel title="▼ Downgrades" tone="#ef4444" movers={downs} up={false} />
      </div>
      <div className="border-t border-base-600 px-5 py-2 text-[11px] text-slate-500">
        A stock lists here when its composite (fundamental + technical + momentum + quality) score
        moves ≥1 point vs the previous refresh. Model-derived · not investment advice.
      </div>
    </div>
  );
}
