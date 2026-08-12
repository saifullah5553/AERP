import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";

import { api } from "@/lib/api";
import { fmtNumber } from "@/lib/format";
import type { ScreenerRow } from "@/types/api";

// The four filters, and nothing else on this page. It answers one question - where is price
// disagreeing with force or momentum - and a page that answers one question well is worth more
// than a second copy of the main screener with extra columns.
const FILTERS = [
  { key: "div_rsi_bullish", label: "RSI bullish", tone: "#22c55e",
    hint: "price made a lower low, RSI made a higher low" },
  { key: "div_rsi_bearish", label: "RSI bearish", tone: "#ef4444",
    hint: "price made a higher high, RSI made a lower high" },
  { key: "div_efi_bullish", label: "EFI bullish", tone: "#22c55e",
    hint: "price made a lower low, Elder's Force Index made a higher low" },
  { key: "div_efi_bearish", label: "EFI bearish", tone: "#ef4444",
    hint: "price made a higher high, Elder's Force Index made a lower high" },
] as const;

type FilterKey = (typeof FILTERS)[number]["key"];

// Display order and the label each market is known by. Grouping the results BY MARKET is the
// point of the page: the question is "which Pakistani stocks have diverged", not "which stocks
// have diverged, and by the way here is a country column you can squint at".
const MARKETS: { key: string; label: string }[] = [
  { key: "psx", label: "Pakistan (PSX)" },
  { key: "us", label: "US" },
  { key: "india", label: "India (NSE)" },
  { key: "australia", label: "Australia (ASX)" },
  { key: "gcc", label: "Saudi (Tadawul)" },
  { key: "dfm", label: "Dubai (DFM)" },
];

export default function TechnicalFilterPage() {
  const [rows, setRows] = useState<ScreenerRow[] | null>(null);
  // Every filter ON at first load. The page's job is to show what has diverged; making the
  // trader tick four boxes before it shows anything is a blank screen pretending to be a tool.
  const [active, setActive] = useState<Set<FilterKey>>(
    () => new Set(FILTERS.map((f) => f.key)),
  );
  const [market, setMarket] = useState("all");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const ctrl = new AbortController();
    // One page big enough to hold the universe. The static build filters in the browser
    // anyway, and this page needs the whole set to count matches per filter.
    api
      .screener({ page: 1, page_size: 20000 }, ctrl.signal)
      .then((r) => setRows(r.items))
      .catch((e) => {
        if ((e as Error).name !== "AbortError") setError("Could not load the universe.");
      })
      .finally(() => setLoading(false));
    return () => ctrl.abort();
  }, []);

  const matched = useMemo(() => {
    if (!rows) return [];
    // ANY of the selected filters, not all. Asking for a bullish RSI divergence AND a bearish
    // EFI one at the same time is a contradiction that would always return nothing; a trader
    // ticking two boxes means "show me either".
    const out = rows.filter((r) => {
      if (market !== "all" && r.region !== market) return false;
      if (active.size === 0) return false;
      return [...active].some((k) => Boolean((r as unknown as Record<string, unknown>)[k]));
    });
    out.sort((a, b) => String(b.div_latest ?? "").localeCompare(String(a.div_latest ?? "")));
    return out;
  }, [rows, active, market]);

  // Grouped by market, in display order, empty markets dropped.
  const grouped = useMemo(() => {
    const by = new Map<string, ScreenerRow[]>();
    for (const r of matched) {
      const key = String(r.region ?? "other");
      if (!by.has(key)) by.set(key, []);
      by.get(key)!.push(r);
    }
    const known = MARKETS.filter((m) => by.has(m.key)).map((m) => ({
      key: m.key, label: m.label, rows: by.get(m.key)!,
    }));
    // Anything the list above has not heard of still appears, at the end - the same rule the
    // quarterly history learned when Dubai went missing for want of a hardcoded entry.
    const extra = [...by.keys()]
      .filter((k) => !MARKETS.some((m) => m.key === k))
      .map((k) => ({ key: k, label: k.toUpperCase(), rows: by.get(k)! }));
    return [...known, ...extra];
  }, [matched]);

  const toggle = (k: FilterKey) => {
    const next = new Set(active);
    if (next.has(k)) next.delete(k);
    else next.add(k);
    setActive(next);
  };

  return (
    <div className="flex h-full flex-col bg-base-900 text-slate-200">
      <header className="flex flex-wrap items-center gap-3 border-b border-base-600 bg-base-900 px-5 py-3">
        <Link to="/" className="text-sm text-slate-400 hover:text-accent">← Dashboard</Link>
        <span className="text-lg font-bold text-slate-100">Divergence Stocks</span>
        <span className="text-xs text-slate-500">RSI &amp; Elder Force Index divergences</span>
        <select
          value={market}
          onChange={(e) => setMarket(e.target.value)}
          className="ml-auto rounded border border-base-500 bg-base-700 px-2 py-1 text-xs text-slate-200"
        >
          <option value="all">All markets</option>
          {MARKETS.map((m) => <option key={m.key} value={m.key}>{m.label}</option>)}
        </select>
      </header>

      <div className="flex flex-wrap gap-2 border-b border-base-600 px-5 py-3">
        {FILTERS.map((f) => {
          const on = active.has(f.key);
          const count = rows
            ? rows.filter(
                (r) =>
                  (market === "all" || r.region === market) &&
                  Boolean((r as unknown as Record<string, unknown>)[f.key]),
              ).length
            : 0;
          return (
            <button
              key={f.key}
              onClick={() => toggle(f.key)}
              title={f.hint}
              className={`rounded-full border px-3 py-1.5 text-xs font-semibold transition-colors ${
                on ? "border-accent bg-accent/20" : "border-base-500 bg-base-700 hover:bg-base-600"
              }`}
              style={{ color: on ? f.tone : undefined }}
            >
              {f.label} <span className="ml-1 text-slate-500">{count}</span>
            </button>
          );
        })}
      </div>

      <div className="mx-auto w-full max-w-6xl px-4 pt-3">
        {/* Said plainly, because a divergence is a warning that momentum is thinning, not an
            instruction. It can persist for months while price keeps going. */}
        <div className="rounded-lg border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-[11px] text-slate-300">
          <b>A divergence is a condition, not a signal.</b> It says price and the oscillator
          disagree at two confirmed swing points — momentum thinning under a rally, or selling
          losing force under a decline. It can persist for months while price continues, and it
          resolves as often by the oscillator catching up as by price turning. Both are measured
          on confirmed swings, so the newest few bars can never anchor one.
        </div>
      </div>

      <div className="min-h-0 flex-1 overflow-auto p-4">
        {loading ? (
          <div className="p-8 text-center text-sm text-slate-500">Loading…</div>
        ) : error ? (
          <div className="p-8 text-center text-sm text-red-400">{error}</div>
        ) : active.size === 0 ? (
          <div className="p-8 text-center text-sm text-slate-500">
            Choose one or more divergences above. Selecting several shows anything matching any
            of them.
          </div>
        ) : matched.length === 0 ? (
          <div className="p-8 text-center text-sm text-slate-500">
            Nothing matches in this market right now — which is a real answer, not an error.
          </div>
        ) : (
          <div className="space-y-5">
            {grouped.map((g) => (
              <section key={g.key}>
                <div className="mb-1.5 flex items-baseline gap-3 px-1">
                  <h3 className="text-sm font-bold text-slate-100">{g.label}</h3>
                  <span className="text-xs text-slate-500">
                    {g.rows.length} {g.rows.length === 1 ? "stock" : "stocks"}
                  </span>
                </div>
                <div className="overflow-x-auto rounded-lg border border-base-600">
                  <table className="w-full text-sm">
                    <thead className="bg-base-800 text-[10px] uppercase tracking-wide text-slate-400">
                      <tr>
                        <th className="px-3 py-2 text-left">Ticker</th>
                        <th className="px-3 py-2 text-left">Company</th>
                        <th className="px-3 py-2 text-left">Sector</th>
                        <th className="px-3 py-2 text-right">Price</th>
                        <th className="px-3 py-2 text-left">Divergences</th>
                        <th className="px-3 py-2 text-right">Confirmed</th>
                      </tr>
                    </thead>
                    <tbody>
                      {g.rows.map((r) => (
                        <tr key={r.provider_symbol ?? r.symbol}
                            className="border-t border-base-700/40 hover:bg-base-700/40">
                          <td className="px-3 py-1.5 font-semibold text-accent">
                            <Link to={`/company/${r.provider_symbol ?? r.symbol}`}>{r.symbol}</Link>
                          </td>
                          <td className="max-w-[240px] truncate px-3 py-1.5 text-xs text-slate-400"
                              title={r.name ?? ""}>{r.name ?? "—"}</td>
                          <td className="max-w-[170px] truncate px-3 py-1.5 text-xs text-slate-500"
                              title={r.sector ?? ""}>{r.sector ?? "—"}</td>
                          <td className="num px-3 py-1.5 text-right">{fmtNumber(r.price)}</td>
                          <td className="px-3 py-1.5">
                            {FILTERS.filter((f) =>
                              Boolean((r as unknown as Record<string, unknown>)[f.key]),
                            ).map((f) => (
                              <span key={f.key}
                                    className="mr-1 rounded px-1.5 py-0.5 text-[10px] font-bold"
                                    style={{ background: `${f.tone}22`, color: f.tone }}>
                                {f.label}
                              </span>
                            ))}
                          </td>
                          <td className="num px-3 py-1.5 text-right text-[11px] text-slate-500">
                            {r.div_latest ?? "—"}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </section>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
