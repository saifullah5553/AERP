import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";

import { api } from "@/lib/api";
import { type Alert, buildAlerts } from "@/lib/alerts";
import type { CatalystsData, ScreenerRow } from "@/types/api";
import { AlertRow } from "./NotificationBell";

const KINDS = ["All", "Announcement", "Corporate Action", "Insider", "Market Event"];

// Full-page market-alerts feed: recent PSX announcements/corporate actions (each links to
// the original PSX PDF), notable insider activity, and the PK macro calendar.
export default function AlertsPage() {
  const [cat, setCat] = useState<CatalystsData | null>(null);
  const [rows, setRows] = useState<ScreenerRow[]>([]);
  const [kind, setKind] = useState("All");

  useEffect(() => {
    const ctrl = new AbortController();
    api.catalysts(ctrl.signal).then(setCat).catch(() => setCat(null));
    api
      .screener({ page: 1, page_size: 5000 }, ctrl.signal)
      .then((p) => setRows(p.items))
      .catch(() => setRows([]));
    return () => ctrl.abort();
  }, []);

  const all = useMemo(() => buildAlerts(cat, rows), [cat, rows]);
  const alerts: Alert[] = kind === "All" ? all : all.filter((a) => a.kind === kind);

  return (
    <div className="flex h-full flex-col bg-base-900 text-slate-200">
      <header className="flex flex-wrap items-center gap-3 border-b border-base-600 bg-base-900 px-5 py-3">
        <Link to="/" className="text-sm text-slate-400 hover:text-accent">← Dashboard</Link>
        <span className="text-lg font-bold text-slate-100">Market Alerts</span>
        <span className="rounded bg-base-700 px-2 py-0.5 text-xs text-slate-400">{all.length} recent</span>
        <div className="ml-auto flex flex-wrap gap-1.5">
          {KINDS.map((k) => (
            <button
              key={k}
              onClick={() => setKind(k)}
              className={`rounded-full border px-2.5 py-0.5 text-xs font-medium transition-colors ${
                kind === k
                  ? "border-accent bg-accent/20 text-accent"
                  : "border-base-500 bg-base-700 text-slate-300 hover:bg-base-600"
              }`}
            >
              {k}
            </button>
          ))}
        </div>
      </header>

      <div className="min-h-0 flex-1 overflow-y-auto">
        {alerts.length === 0 ? (
          <div className="p-8 text-center text-sm text-slate-500">No alerts in this category.</div>
        ) : (
          <div className="mx-auto max-w-3xl divide-y divide-base-700/50 p-2">
            {alerts.map((a) => <AlertRow key={a.id} a={a} />)}
          </div>
        )}
      </div>
      <div className="border-t border-base-600 px-5 py-2 text-[11px] text-slate-500">
        Announcements &amp; insider from PSX filings · macro from the PK economic calendar · click an
        announcement to open its original PSX document. Research context only — not investment advice.
      </div>
    </div>
  );
}
