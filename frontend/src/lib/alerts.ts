// Shared market-alerts builder used by the header bell and the /alerts page.

import type { CatalystsData } from "@/types/api";

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

export function buildAlerts(cat: CatalystsData | null): Alert[] {
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

  // (Detailed insider transactions are shown as a dedicated table on the Alerts page,
  //  sourced from insider.json — not the screener's coarse activity flag.)

  out.sort((a, b) => (b.date ?? "0").localeCompare(a.date ?? "0"));
  return out;
}
