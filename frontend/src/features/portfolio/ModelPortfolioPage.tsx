import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";

import { api } from "@/lib/api";
import { fmtNumber } from "@/lib/format";
import type { ScreenerRow } from "@/types/api";

// Sizing follows the backtests: PSX carried a deeper drawdown at small N (-29.5% at 10 vs
// -20.1% at 20), so it holds more names; the other markets were steadier and hold 15.
// Deliberately NOT tuned to whichever N scored best - that flipped between markets, which is
// how you know it was noise rather than a parameter worth optimising.
const SIZE_BY_MARKET: Record<string, number> = {
  psx: 20, us: 15, india: 15, australia: 15, gcc: 15,
};
const DEFAULT_SIZE = 15;

const MARKETS: { key: string; label: string }[] = [
  { key: "all", label: "All Markets" },
  { key: "psx", label: "Pakistan" },
  { key: "us", label: "US" },
  { key: "india", label: "India" },
  { key: "australia", label: "Australia" },
  { key: "gcc", label: "GCC" },
];

function ActionBadge({ action }: { action?: string | null }) {
  const map: Record<string, { bg: string; fg: string }> = {
    buy: { bg: "rgba(34,197,94,0.18)", fg: "#22c55e" },
    hold: { bg: "rgba(56,189,248,0.16)", fg: "#38bdf8" },
    watch: { bg: "rgba(245,158,11,0.16)", fg: "#f59e0b" },
  };
  const s = action ? map[action] : undefined;
  if (!s) return <span className="text-slate-600">—</span>;
  return (
    <span style={{ background: s.bg, color: s.fg }}
          className="rounded px-2 py-0.5 text-[11px] font-bold uppercase">
      {action}
    </span>
  );
}

function Holdings({ region, rows }: { region: string; rows: ScreenerRow[] }) {
  const size = SIZE_BY_MARKET[region] ?? DEFAULT_SIZE;
  const picks = useMemo(
    () =>
      rows
        .filter((r) => r.region === region && r.quality_score != null
          && r.strategy_action !== "avoid")
        .sort((a, b) => (b.quality_score ?? 0) - (a.quality_score ?? 0))
        .slice(0, size),
    [rows, region, size],
  );
  if (picks.length === 0) return null;

  const label = MARKETS.find((m) => m.key === region)?.label ?? region.toUpperCase();
  return (
    <div className="mb-6">
      <div className="mb-2 flex items-baseline gap-3 px-1">
        <h2 className="text-sm font-bold uppercase tracking-wide text-slate-200">{label}</h2>
        <span className="text-xs text-slate-500">
          top {picks.length} of {size} · equal weight
        </span>
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
              <th className="px-3 py-2 text-left">Action</th>
              <th className="px-3 py-2 text-right">Price</th>
              <th className="px-3 py-2 text-right">Weight</th>
            </tr>
          </thead>
          <tbody>
            {picks.map((r, i) => (
              <tr key={r.provider_symbol} className="border-b border-base-700/40 hover:bg-base-700/40">
                <td className="px-3 py-1.5 text-slate-500">{i + 1}</td>
                <td className="px-3 py-1.5">
                  <Link to={`/company/${encodeURIComponent(r.provider_symbol)}`}
                        className="font-semibold text-accent">
                    {r.symbol}
                  </Link>
                </td>
                <td className="px-3 py-1.5 text-slate-300">
                  <span className="block max-w-[240px] truncate" title={r.name ?? ""}>
                    {r.name ?? "—"}
                  </span>
                </td>
                <td className="px-3 py-1.5 text-xs text-slate-400">{r.sector ?? "—"}</td>
                <td className="num px-3 py-1.5 text-right font-semibold text-slate-200">
                  {r.quality_score?.toFixed(1) ?? "—"}
                </td>
                <td className="px-3 py-1.5"><ActionBadge action={r.strategy_action} /></td>
                <td className="num px-3 py-1.5 text-right text-slate-300">
                  {fmtNumber(r.price)}
                </td>
                <td className="num px-3 py-1.5 text-right text-slate-500">
                  {(100 / picks.length).toFixed(1)}%
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

// Model Portfolio: what the strategy would hold right now — the quality-gated names ranked by
// fundamental score, equal weight. This is the live expression of the backtested approach.
export default function ModelPortfolioPage() {
  const [rows, setRows] = useState<ScreenerRow[]>([]);
  const [market, setMarket] = useState("all");
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const ctrl = new AbortController();
    api
      .screener({ page: 1, page_size: 12000 }, ctrl.signal)
      .then((p) => setRows(p.items ?? []))
      .catch(() => setRows([]))
      .finally(() => setLoading(false));
    return () => ctrl.abort();
  }, []);

  const shown = market === "all"
    ? MARKETS.filter((m) => m.key !== "all").map((m) => m.key)
    : [market];

  return (
    <div className="flex h-full flex-col bg-base-900 text-slate-200">
      <header className="flex flex-wrap items-center gap-3 border-b border-base-600 bg-base-900 px-5 py-3">
        <Link to="/" className="text-sm text-slate-400 hover:text-accent">← Dashboard</Link>
        <span className="text-lg font-bold text-slate-100">Model Portfolio</span>
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
          Holdings are the highest <b>fundamental quality</b> names that pass the gate — growth
          (45%) + cash (40%) + a debt guardrail — ranked by score, equal weight. Pakistan holds
          20, other markets 15. Research output, not investment advice.
        </div>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto p-4">
        {loading ? (
          <div className="p-8 text-center text-sm text-slate-500">Loading…</div>
        ) : (
          <>
            {shown.map((region) => (
              <Holdings key={region} region={region} rows={rows} />
            ))}
            {shown.every(
              (rg) => !rows.some((r) => r.region === rg && r.quality_score != null),
            ) && (
              <div className="p-8 text-center text-sm text-slate-500">
                No quality-scored names yet for this market — the strategy engine fills these
                on the next daily refresh.
              </div>
            )}
          </>
        )}
      </div>
    </div>
  );
}
