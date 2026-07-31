import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";

import { api, type InsiderTx, type SignalMove } from "@/lib/api";
import { buildAlerts, resultsFiled } from "@/lib/alerts";
import { fmtCompact } from "@/lib/format";
import type { CatalystsData } from "@/types/api";
import { AlertRow } from "./NotificationBell";

type Tab = "signals" | "events" | "insider" | "results";

function shares(n: number | null): string {
  return n == null ? "—" : Math.round(n).toLocaleString();
}

function InsiderTable({ rows }: { rows: InsiderTx[] }) {
  if (rows.length === 0) return <div className="p-8 text-center text-sm text-slate-500">No insider transactions.</div>;
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead className="sticky top-0 bg-base-800 text-[10px] uppercase tracking-wide text-slate-400">
          <tr className="border-b border-base-600">
            <th className="px-3 py-2 text-left">Ticker</th>
            <th className="px-3 py-2 text-left">Insider</th>
            <th className="px-3 py-2 text-left">Action</th>
            <th className="px-3 py-2 text-right">Shares</th>
            <th className="px-3 py-2 text-right">Value</th>
            <th className="px-3 py-2 text-left">Market</th>
            <th className="px-3 py-2 text-right">Date</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((t, i) => {
            const buy = t.type === "buy";
            return (
              <tr key={i} className="border-b border-base-700/40 hover:bg-base-700/40">
                <td className="px-3 py-1.5">
                  <Link to={`/company/${encodeURIComponent(t.provider_symbol)}`} className="font-semibold text-accent">
                    {t.symbol}
                  </Link>
                </td>
                <td className="px-3 py-1.5 text-slate-300">
                  <span className="block max-w-[240px] truncate" title={`${t.insider ?? ""}${t.title ? " · " + t.title : ""}`}>
                    {t.insider ?? "—"}
                  </span>
                </td>
                <td className="px-3 py-1.5 font-semibold" style={{ color: buy ? "#22c55e" : "#ef4444" }}>
                  {buy ? "BUY" : "SELL"}
                </td>
                <td className="num px-3 py-1.5 text-right text-slate-300">{shares(t.shares)}</td>
                <td className="num px-3 py-1.5 text-right text-slate-300">{t.value == null ? "—" : fmtCompact(t.value)}</td>
                <td className="px-3 py-1.5 text-[11px] uppercase text-slate-500">{t.region}</td>
                <td className="num px-3 py-1.5 text-right text-[11px] text-slate-500">{t.date}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

const SIG_LABEL: Record<string, string> = {
  strong_buy: "Strong Buy", buy: "Buy", hold: "Hold", sell: "Sell", strong_sell: "Strong Sell",
};

// Stocks that crossed the strong-buy line since the last refresh: entering = time to buy,
// leaving = consider trimming/selling. This is the actionable buy/sell-timing feed.
function SignalMovesTable({ rows }: { rows: SignalMove[] }) {
  if (rows.length === 0)
    return <div className="p-8 text-center text-sm text-slate-500">No strong-buy transitions in the last 30 days.</div>;
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead className="sticky top-0 bg-base-800 text-[10px] uppercase tracking-wide text-slate-400">
          <tr className="border-b border-base-600">
            <th className="px-3 py-2 text-left">Signal</th>
            <th className="px-3 py-2 text-left">Ticker</th>
            <th className="px-3 py-2 text-left">Name</th>
            <th className="px-3 py-2 text-left">Transition</th>
            <th className="px-3 py-2 text-right">Score</th>
            <th className="px-3 py-2 text-left">Market</th>
            <th className="px-3 py-2 text-right">Date</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((m, i) => {
            const buy = m.direction === "buy";
            return (
              <tr key={i} className="border-b border-base-700/40 hover:bg-base-700/40">
                <td className="px-3 py-1.5">
                  <span
                    className="rounded px-2 py-0.5 text-[11px] font-bold"
                    style={{
                      color: buy ? "#22c55e" : "#ef4444",
                      background: buy ? "rgba(34,197,94,0.14)" : "rgba(239,68,68,0.14)",
                    }}
                  >
                    {buy ? "▲ TIME TO BUY" : "▼ TIME TO SELL"}
                  </span>
                </td>
                <td className="px-3 py-1.5">
                  <Link to={`/company/${encodeURIComponent(m.provider_symbol)}`} className="font-semibold text-accent">
                    {m.symbol}
                  </Link>
                </td>
                <td className="px-3 py-1.5 text-slate-300">
                  <span className="block max-w-[220px] truncate" title={m.name ?? ""}>{m.name ?? "—"}</span>
                </td>
                <td className="px-3 py-1.5 text-xs text-slate-400">
                  {SIG_LABEL[m.from] ?? m.from} → <span className="font-semibold text-slate-200">{SIG_LABEL[m.to] ?? m.to}</span>
                </td>
                <td className="num px-3 py-1.5 text-right text-slate-300">{m.composite == null ? "—" : m.composite.toFixed(1)}</td>
                <td className="px-3 py-1.5 text-[11px] uppercase text-slate-500">{m.region}</td>
                <td className="num px-3 py-1.5 text-right text-[11px] text-slate-500">{m.date}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

// Alerts: Announcements & macro events (each links to its PSX PDF) + a cross-market
// Insider Transactions table (real filings for US/India/Australia/PSX).
export default function AlertsPage() {
  const [cat, setCat] = useState<CatalystsData | null>(null);
  const [ins, setIns] = useState<InsiderTx[]>([]);
  const [moves, setMoves] = useState<SignalMove[]>([]);
  const [tab, setTab] = useState<Tab>("signals");
  const [region, setRegion] = useState("all");

  useEffect(() => {
    const ctrl = new AbortController();
    api.catalysts(ctrl.signal).then(setCat).catch(() => setCat(null));
    api.insiderFeed(ctrl.signal).then(setIns).catch(() => setIns([]));
    api
      .signalMoves(ctrl.signal)
      .then((d) => setMoves([...d.buy, ...d.sell].sort((a, b) => (a.date < b.date ? 1 : -1))))
      .catch(() => setMoves([]));
    return () => ctrl.abort();
  }, []);

  const alerts = useMemo(() => buildAlerts(cat), [cat]);
  const since = useMemo(() => new Date(Date.now() - 100 * 86400000).toISOString().slice(0, 10), []);
  const results = useMemo(() => resultsFiled(cat, since), [cat, since]);
  const regions = useMemo(() => ["all", ...[...new Set(ins.map((t) => t.region))].sort()], [ins]);
  const insider = region === "all" ? ins : ins.filter((t) => t.region === region);

  const tabBtn = (id: Tab, label: string) => (
    <button
      onClick={() => setTab(id)}
      className={`rounded-full px-3 py-1 text-xs font-semibold transition-colors ${
        tab === id ? "bg-accent/20 text-accent" : "text-slate-400 hover:text-slate-200"
      }`}
    >
      {label}
    </button>
  );

  return (
    <div className="flex h-full flex-col bg-base-900 text-slate-200">
      <header className="flex flex-wrap items-center gap-3 border-b border-base-600 bg-base-900 px-5 py-3">
        <Link to="/" className="text-sm text-slate-400 hover:text-accent">← Dashboard</Link>
        <span className="text-lg font-bold text-slate-100">Market Alerts</span>
        <div className="flex items-center gap-1 rounded-full border border-base-600 p-0.5">
          {tabBtn("signals", `Buy / Sell Signals (${moves.length})`)}
          {tabBtn("events", `Announcements (${alerts.length})`)}
          {tabBtn("insider", `Insider (${ins.length})`)}
          {tabBtn("results", `Results Filed (${results.length})`)}
        </div>
        {tab === "insider" && (
          <div className="ml-auto flex flex-wrap gap-1.5">
            {regions.map((r) => (
              <button
                key={r}
                onClick={() => setRegion(r)}
                className={`rounded-full border px-2.5 py-0.5 text-xs font-medium uppercase ${
                  region === r ? "border-accent bg-accent/20 text-accent" : "border-base-500 bg-base-700 text-slate-300 hover:bg-base-600"
                }`}
              >
                {r}
              </button>
            ))}
          </div>
        )}
      </header>

      <div className="min-h-0 flex-1 overflow-y-auto">
        {tab === "signals" && (
          <div>
            <div className="mx-auto max-w-3xl px-2 pt-3">
              <div className="rounded-lg border border-accent/30 bg-accent/10 px-3 py-2 text-[11px] text-slate-300">
                Stocks that <span className="font-semibold text-up">entered Strong Buy</span> (time to buy)
                or <span className="font-semibold text-down">dropped out of Strong Buy</span> (time to sell / trim),
                over the last 30 days. Research context only — not investment advice.
              </div>
            </div>
            <SignalMovesTable rows={moves} />
          </div>
        )}
        {tab === "events" && (
          alerts.length === 0 ? (
            <div className="p-8 text-center text-sm text-slate-500">No announcements.</div>
          ) : (
            <div className="mx-auto max-w-3xl divide-y divide-base-700/50 p-2">
              {alerts.map((a) => <AlertRow key={a.id} a={a} />)}
            </div>
          )
        )}
        {tab === "insider" && <InsiderTable rows={insider} />}
        {tab === "results" && (
          <div className="mx-auto max-w-3xl p-2">
            <div className="mb-2 rounded-lg border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-[11px] text-amber-200/90">
              PSX companies that filed results in the last ~100 days. Re-export these companies'
              financials (stockanalysis CSV) during results season — the pipeline recomputes
              fundamentals + scores automatically on the next refresh.
            </div>
            {results.length === 0 ? (
              <div className="p-8 text-center text-sm text-slate-500">No results filed recently.</div>
            ) : (
              <div className="divide-y divide-base-700/50">
                {results.map((r) => (
                  <div key={r.symbol} className="flex items-center justify-between gap-3 px-3 py-2">
                    <div className="min-w-0">
                      <Link to={`/company/${encodeURIComponent(r.symbol + ".KA")}`} className="font-semibold text-accent">
                        {r.symbol}
                      </Link>
                      <span className="ml-2 truncate text-xs text-slate-400">{r.title}</span>
                    </div>
                    <div className="flex shrink-0 items-center gap-3">
                      {r.url && (
                        <a href={r.url} target="_blank" rel="noreferrer" className="text-[11px] font-semibold text-accent hover:underline">
                          PDF ↗
                        </a>
                      )}
                      <span className="num text-[11px] text-slate-500">{r.date}</span>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}
      </div>
      <div className="border-t border-base-600 px-5 py-2 text-[11px] text-slate-500">
        Announcements link to the original PSX document. Insider = open-market filings
        (US SEC / PSX / NSE / ASX). Research context only — not investment advice.
      </div>
    </div>
  );
}
