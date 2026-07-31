import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";

import { api, type InsiderTx } from "@/lib/api";
import { buildAlerts } from "@/lib/alerts";
import { fmtCompact } from "@/lib/format";
import type { CatalystsData } from "@/types/api";
import { AlertRow } from "./NotificationBell";

type Tab = "events" | "insider";

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

// Alerts: Announcements & macro events (each links to its PSX PDF) + a cross-market
// Insider Transactions table (real filings for US/India/Australia/PSX).
export default function AlertsPage() {
  const [cat, setCat] = useState<CatalystsData | null>(null);
  const [ins, setIns] = useState<InsiderTx[]>([]);
  const [tab, setTab] = useState<Tab>("events");
  const [region, setRegion] = useState("all");

  useEffect(() => {
    const ctrl = new AbortController();
    api.catalysts(ctrl.signal).then(setCat).catch(() => setCat(null));
    api.insiderFeed(ctrl.signal).then(setIns).catch(() => setIns([]));
    return () => ctrl.abort();
  }, []);

  const alerts = useMemo(() => buildAlerts(cat), [cat]);
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
          {tabBtn("events", `Announcements (${alerts.length})`)}
          {tabBtn("insider", `Insider (${ins.length})`)}
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
        {tab === "events" ? (
          alerts.length === 0 ? (
            <div className="p-8 text-center text-sm text-slate-500">No announcements.</div>
          ) : (
            <div className="mx-auto max-w-3xl divide-y divide-base-700/50 p-2">
              {alerts.map((a) => <AlertRow key={a.id} a={a} />)}
            </div>
          )
        ) : (
          <InsiderTable rows={insider} />
        )}
      </div>
      <div className="border-t border-base-600 px-5 py-2 text-[11px] text-slate-500">
        Announcements link to the original PSX document. Insider = open-market filings
        (US SEC / PSX / NSE / ASX). Research context only — not investment advice.
      </div>
    </div>
  );
}
