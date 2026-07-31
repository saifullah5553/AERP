import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { api, type Mover, type MoversData } from "@/lib/api";
import { fmtSnapshotAge } from "@/lib/format";

function MoverRow({ m, up }: { m: Mover; up: boolean }) {
  const color = up ? "#22c55e" : "#ef4444";
  return (
    <Link
      to={`/company/${encodeURIComponent(m.provider_symbol)}`}
      className="flex items-center justify-between gap-3 px-3 py-2 hover:bg-base-700/40"
    >
      <div className="min-w-0">
        <span className="font-semibold text-accent">{m.symbol}</span>
        <span className="ml-2 truncate text-xs text-slate-400">{m.name}</span>
        <span className="ml-2 rounded bg-base-700 px-1 py-0.5 text-[9px] uppercase text-slate-500">{m.region}</span>
      </div>
      <div className="num flex shrink-0 items-center gap-3 text-sm">
        <span className="text-slate-400">{m.prev} → {m.composite}</span>
        <span className="w-14 text-right font-bold" style={{ color }}>
          {up ? "+" : ""}{m.delta}
        </span>
      </div>
    </Link>
  );
}

function Panel({ title, tone, movers, up }: { title: string; tone: string; movers: Mover[]; up: boolean }) {
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
        <div className="divide-y divide-base-700/50 overflow-y-auto">
          {movers.map((m) => <MoverRow key={m.provider_symbol} m={m} up={up} />)}
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
