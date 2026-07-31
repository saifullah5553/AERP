// Shared market-alerts builder used by the header bell and the /alerts page.

import type { CatalystsData, ScreenerRow } from "@/types/api";

export interface Alert {
  id: string;
  kind: string;
  icon: string;
  color: string;
  title: string;
  sub: string;
  date: string | null;
  url?: string | null; // original PSX PDF / source document, when available
}

export function buildAlerts(cat: CatalystsData | null, rows: ScreenerRow[]): Alert[] {
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
        url: e.pdf_url ?? null,
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
        date: typeof r.scored_on === "string" ? r.scored_on.slice(0, 10) : null,
      });
    }
  }

  out.sort((a, b) => (b.date ?? "0").localeCompare(a.date ?? "0"));
  return out;
}
