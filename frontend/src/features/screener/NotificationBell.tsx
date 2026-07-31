import { useEffect, useMemo, useState } from "react";

import { api } from "@/lib/api";
import { type Alert, buildAlerts } from "@/lib/alerts";
import type { CatalystsData } from "@/types/api";

const SEEN_KEY = "aerp-seen-alerts";

function loadSeen(): Set<string> {
  try {
    return new Set(JSON.parse(localStorage.getItem(SEEN_KEY) || "[]"));
  } catch {
    return new Set();
  }
}

export function AlertRow({ a }: { a: Alert }) {
  const inner = (
    <>
      <span className="mt-0.5 text-sm">{a.icon}</span>
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2">
          <span className="text-sm font-semibold" style={{ color: a.color }}>{a.title}</span>
          <span className="rounded bg-base-700 px-1.5 py-0.5 text-[9px] uppercase tracking-wide text-slate-400">
            {a.kind}
          </span>
          {a.url && <span className="text-[9px] text-accent">PDF ↗</span>}
        </div>
        <div className="truncate text-[11px] text-slate-400" title={a.sub}>{a.sub}</div>
      </div>
      {a.date && <span className="num shrink-0 text-[10px] text-slate-500">{a.date}</span>}
    </>
  );
  const cls = "flex items-start gap-2.5 px-3 py-2 hover:bg-base-700/40";
  return a.url ? (
    <a href={a.url} target="_blank" rel="noreferrer" className={cls}>{inner}</a>
  ) : (
    <div className={cls}>{inner}</div>
  );
}

export default function NotificationBell() {
  const [cat, setCat] = useState<CatalystsData | null>(null);
  const [open, setOpen] = useState(false);
  const [seen, setSeen] = useState<Set<string>>(() => loadSeen());

  useEffect(() => {
    const ctrl = new AbortController();
    api.catalysts(ctrl.signal).then(setCat).catch(() => setCat(null));
    return () => ctrl.abort();
  }, []);

  const alerts = useMemo(() => buildAlerts(cat).slice(0, 40), [cat]);
  const unread = alerts.filter((a) => !seen.has(a.id)).length;

  const toggle = () => {
    const next = !open;
    setOpen(next);
    if (next) {
      const ids = alerts.map((a) => a.id);
      try {
        localStorage.setItem(SEEN_KEY, JSON.stringify(ids));
      } catch {
        /* ignore */
      }
      setSeen(new Set(ids));
    }
  };

  if (alerts.length === 0) return null;

  return (
    <div className="relative">
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
              <a href="#/alerts" className="text-[10px] font-semibold text-accent hover:underline" onClick={() => setOpen(false)}>
                View all →
              </a>
            </div>
            <div className="divide-y divide-base-700/50">
              {alerts.map((a) => <AlertRow key={a.id} a={a} />)}
            </div>
            <div className="border-t border-base-600 px-3 py-1.5 text-[10px] text-slate-500">
              Announcements &amp; insider from PSX filings · click an item to open its PSX document
            </div>
          </div>
        </>
      )}
    </div>
  );
}
