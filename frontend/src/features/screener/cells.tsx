import type { ICellRendererParams } from "ag-grid-community";

import { fmtChangePct, fmtScore, titleize } from "@/lib/format";
import type { SignalType } from "@/types/api";

const SIGNAL_STYLE: Record<SignalType, { bg: string; fg: string; label: string }> = {
  strong_buy: { bg: "#064e3b", fg: "#4ade80", label: "Strong Buy" },
  buy: { bg: "#065f46", fg: "#6ee7b7", label: "Buy" },
  hold: { bg: "#334155", fg: "#cbd5e1", label: "Hold" },
  sell: { bg: "#7f1d1d", fg: "#fca5a5", label: "Sell" },
  strong_sell: { bg: "#991b1b", fg: "#fecaca", label: "Strong Sell" },
};

export function SignalCell(p: ICellRendererParams) {
  const sig = p.value as SignalType | null;
  if (!sig) return <span className="text-slate-600">—</span>;
  const s = SIGNAL_STYLE[sig];
  return (
    <span
      style={{ background: s.bg, color: s.fg }}
      className="inline-block rounded px-2 py-0.5 text-xs font-semibold"
    >
      {s.label}
    </span>
  );
}

// Strategy action: the quality gate's verdict. Green = act, amber = watchlist, grey = skip.
const ACTION_STYLE: Record<string, { bg: string; fg: string; label: string }> = {
  buy: { bg: "rgba(34,197,94,0.18)", fg: "#22c55e", label: "BUY" },
  hold: { bg: "rgba(56,189,248,0.16)", fg: "#38bdf8", label: "HOLD" },
  watch: { bg: "rgba(245,158,11,0.16)", fg: "#f59e0b", label: "WATCH" },
  avoid: { bg: "rgba(100,116,139,0.16)", fg: "#94a3b8", label: "AVOID" },
};

export function ActionCell(p: ICellRendererParams) {
  const a = String(p.value ?? "");
  const s = ACTION_STYLE[a];
  if (!s) return <span className="text-slate-600">—</span>;
  return (
    <span
      style={{ background: s.bg, color: s.fg }}
      className="inline-block rounded px-2 py-0.5 text-xs font-bold"
    >
      {s.label}
    </span>
  );
}

// Quality trend across the stored TTM points: is the business getting stronger or weaker?
// Six levels, fitted across the whole 20-period history rather than read off its endpoints.
// The three "strong" and "mixed" labels are new; without them those rows rendered as an
// em-dash, so the companies moving fastest were the ones showing nothing.
const TREND_STYLE: Record<string, { fg: string; label: string }> = {
  strongly_improving: { fg: "#16a34a", label: "▲▲ Strongly improving" },
  improving: { fg: "#22c55e", label: "▲ Improving" },
  stable: { fg: "#94a3b8", label: "→ Stable" },
  // Not "unknown": a company that ran 50 → 80 → 50 has a real and important trajectory. It is
  // simply not a direction, and calling it stable was the previous answer.
  mixed: { fg: "#eab308", label: "↕ Mixed" },
  deteriorating: { fg: "#ef4444", label: "▼ Declining" },
  strongly_deteriorating: { fg: "#dc2626", label: "▼▼ Strongly declining" },
};

export function TrendCell(p: ICellRendererParams) {
  const s = TREND_STYLE[String(p.value ?? "")];
  if (!s) return <span className="text-slate-600">—</span>;
  const chg = (p.data as { quality_change?: number | null } | undefined)?.quality_change;
  return (
    <span style={{ color: s.fg }} className="text-xs font-semibold" title={
      chg == null ? undefined : `quality score change over the series: ${chg > 0 ? "+" : ""}${chg}`
    }>
      {s.label}
    </span>
  );
}

function scoreTones(v: number): { bg: string; border: string } {
  const hue = Math.max(0, Math.min(120, (v / 100) * 120)); // 0=red → 120=green
  return {
    bg: `hsla(${hue}, 70%, 45%, 0.28)`,
    border: `hsla(${hue}, 70%, 50%, 0.7)`,
  };
}

export function ScoreCell(p: ICellRendererParams) {
  const v = p.value as number | null;
  if (v === null || v === undefined) return <span className="text-slate-600">—</span>;
  const t = scoreTones(v);
  // Text uses the theme foreground var so it stays readable on both dark and light.
  return (
    <span
      className="num inline-flex min-w-[2.6rem] items-center justify-center rounded-md px-2 py-0.5 text-xs font-bold tabular-nums"
      style={{ background: t.bg, color: "var(--app-fg)", border: `1px solid ${t.border}` }}
    >
      {fmtScore(v)}
    </span>
  );
}

export function ChangeCell(p: ICellRendererParams) {
  const v = p.value as number | null;
  if (v === null || v === undefined) return <span className="text-slate-600">—</span>;
  const color = v > 0 ? "#22c55e" : v < 0 ? "#ef4444" : "#94a3b8";
  return (
    <span className="num tabular-nums" style={{ color }}>
      {fmtChangePct(v)}
    </span>
  );
}

export function PatternCell(p: ICellRendererParams) {
  const v = p.value as string | null;
  if (!v) return <span className="text-slate-600">—</span>;
  return <span className="text-accent">{titleize(v)}</span>;
}

/** Calendar quarter key for a period-end date: "2026-Q2". */
function quarterKeyOf(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  return `${d.getFullYear()}-Q${Math.floor(d.getMonth() / 3) + 1}`;
}

/**
 * One quarter's fundamental score, with its move against the previous quarter.
 *
 * Each column owns a quarter and looks its own value up, so a company reporting on an
 * off-calendar year still lands in the right column - matching by position would silently
 * shift a whole history sideways.
 */
export function QuarterScoreCell(p: ICellRendererParams & { quarterKey?: string }) {
  const row = p.data as
    | { score_history?: number[] | null; score_history_dates?: string[] | null }
    | undefined;
  const scores = row?.score_history ?? [];
  const dates = row?.score_history_dates ?? [];
  const want = p.quarterKey;
  if (!want || scores.length === 0) return <span className="text-slate-700">·</span>;

  const idx = dates.findIndex((d) => quarterKeyOf(d) === want);
  if (idx < 0 || typeof scores[idx] !== "number") {
    return <span className="text-slate-700">·</span>;
  }

  const score = scores[idx];
  // Stored oldest -> newest, so the prior quarter is the entry before it.
  const prior = idx > 0 ? scores[idx - 1] : null;
  const delta = prior == null ? null : score - prior;

  // Under a point is noise; an arrow asserting direction for it would be worse than none.
  const mark =
    delta == null ? null
      : delta > 1 ? { glyph: "▲", color: "#22c55e" }
      : delta < -1 ? { glyph: "▼", color: "#ef4444" }
      : { glyph: "▬", color: "#64748b" };

  return (
    <span
      className="num text-xs font-semibold"
      style={{ color: scoreColor(score) }}
      title={
        `${dates[idx]}: ${score.toFixed(1)}` +
        (delta == null ? "" : ` (${delta > 0 ? "+" : ""}${delta.toFixed(1)} vs prior quarter)`)
      }
    >
      {score.toFixed(0)}
      {mark && <span style={{ color: mark.color }} className="ml-0.5">{mark.glyph}</span>}
    </span>
  );
}

function scoreColor(v: number): string {
  const hue = Math.max(0, Math.min(120, (v / 100) * 120));
  return `hsl(${hue}, 70%, 60%)`;
}
