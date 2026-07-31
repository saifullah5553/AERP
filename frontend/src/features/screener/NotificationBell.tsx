import { useEffect, useMemo, useRef, useState } from "react";

import { api } from "@/lib/api";
import type { CatalystsData, ScreenerRow } from "@/types/api";

interface Alert {
  id: string;
  kind: string;
  icon: string;
  color: string;
  title: string;
  sub: string;
  date: string | null;
}

const SEEN_KEY = "aerp-seen-alerts";

function loadSeen(): Set<string> {
  try {
    return new Set(JSON.parse(localStorage.getItem(SEEN_KEY) || "[]"));
  } catch {
    return new Set();
  }
}

function buildAlerts(cat: CatalystsData | null, rows: ScreenerRow[]): Alert[] {
  const out: Alert[] = [];

  // Company announcements + corporate actions (results, board meetings, disclosures…).
  for (const [sym, evs] of Object.entries(cat?.by_symbol ?? {})) {
    for (const e of evs) {
      const corp = e.type === "corporate_action";
      out.push({
        id: `ann:${sym}:${e.title}:${e.date ?? ""}`,
        kind: corp ? "Corporate Action" : "Announcement",
        icon: corp ? "💠" : "📄",
        color: "#38bdf8",
        title: sym,
        sub: e.title,
        date: e.date ?? null,
      });
    }
  }

  // Upcoming macro / market events (PK calendar).
  for (const e of cat?.market_events ?? []) {
    out.push({
      id: `evt:${e.title}:${e.date ?? ""}`,
      kind: "Market Event",
      icon: "🔔",
      color: "#a78bfa",
      title: e.title,
      sub: e.note || e.category || "",
      date: e.date ?? null,
    });
  }

  // Notable insider activity.
  for (const r of rows) {
    const act = r.insider_activity;
    if (act === "strong_buying" || act === "strong_selling") {
      const buy = act === "strong_buying";
      out.push({
        id: `ins:${r.symbol}:${act}`,
        kind: "Insider",
        icon: buy ? "🟢" : "🔴",
        color: buy ? "#22c55e" : "#ef4444",
        title: r.symbol,
        sub: buy ? "Strong insider buying" : "Strong insider selling",
        date: r.scored_on ? r.scored_on.slice(0, 10) : null,
      });
    }
  }

  // Sort newest/soonest first (dated first, by date desc; undated last).
  out.sort((a, b) => (b.date ?? "0").localeCompare(a.date ?? "0"));
  return out;
}

export default function NotificationBell() {
  const [cat, setCat] = useState<CatalystsData | null>(null);
  const [rows, setRows] = useState<ScreenerRow[]>([]);
  const [open, setOpen] = useState(false);
  const [seen, setSeen] = useState<Set<string>>(() => loadSeen());
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const ctrl = new AbortController();
    api.catalysts(ctrl.signal).then(setCat).catch(() => setCat(null));
    api
      .screener({ page: 1, page_size: 5000 }, ctrl.signal)
      .then((p) => setRows(p.items))
      .catch(() => setRows([]));
    return () => ctrl.abort();
  }, []);

  const alerts = useMemo(() => buildAlerts(cat, rows).slice(0, 40), [cat, rows]);
  const unread = alerts.filter((a) => !seen.has(a.id)).length;

  const markSeen = () => {
    const ids = alerts.map((a) => a.id);
    try {
      localStorage.setItem(SEEN_KEY, JSON.stringify(ids));
    } catch {
      /* ignore */
    }
    setSeen(new Set(ids));
  };

  const toggle = () => {
    const next = !open;
    setOpen(next);
    if (next) markSeen();
  };

  if (alerts.length === 0) return null;

  return (
    <div className="relative" ref={ref}>
      <button
        onClick={toggle}
        title="Market alerts"
        className="relative flex items-center gap-1 rounded-full border border-base-500 bg-base-700 px-2.5 py-1 text-xs font-semibold text-slate-300 hover:bg-base-600"
      >
        <span className="text-sm leading-none">🔔</span>
        Alerts
        {unread > 0 && (
          <span className="absolute -right-1 -top-1 flex h-4 min-w-[16px] items-center justify-center rounded-full bg-rose-500 px-1 text-[9px] font-bold text-white">
            {unread > 9 ? "9+" : unread}
          </span>
        )}
      </button>

      {open && (
        <>
          <div className="fixed inset-0 z-20" onClick={() => setOpen(false)} />
          <div className="absolute right-0 z-30 mt-2 max-h-[70vh] w-[360px] overflow-y-auto rounded-lg border border-base-500 bg-base-800 shadow-2xl">
            <div className="sticky top-0 flex items-center justify-between border-b border-base-600 bg-base-800 px-3 py-2">
              <span className="text-xs font-bold uppercase tracking-wide text-slate-300">Market Alerts</span>
              <span className="text-[10px] text-slate-500">{alerts.length} recent</span>
            </div>
            <div className="divide-y divide-base-700/50">
              {alerts.map((a) => (
                <div key={a.id} className="flex items-start gap-2.5 px-3 py-2 hover:bg-base-700/40">
                  <span className="mt-0.5 text-sm">{a.icon}</span>
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2">
                      <span className="text-sm font-semibold" style={{ color: a.color }}>{a.title}</span>
                      <span className="rounded bg-base-700 px-1.5 py-0.5 text-[9px] uppercase tracking-wide text-slate-400">
                        {a.kind}
                      </span>
                    </div>
                    <div className="truncate text-[11px] text-slate-400" title={a.sub}>{a.sub}</div>
                  </div>
                  {a.date && <span className="num shrink-0 text-[10px] text-slate-500">{a.date}</span>}
                </div>
              ))}
            </div>
            <div className="border-t border-base-600 px-3 py-1.5 text-[10px] text-slate-500">
              Announcements &amp; insider from PSX filings · macro from PK calendar · research context only
            </div>
          </div>
        </>
      )}
    </div>
  );
}
