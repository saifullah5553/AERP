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
const TREND_STYLE: Record<string, { fg: string; label: string }> = {
  improving: { fg: "#22c55e", label: "▲ Improving" },
  stable: { fg: "#94a3b8", label: "→ Stable" },
  deteriorating: { fg: "#ef4444", label: "▼ Declining" },
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

// "30 Jun 26" - short enough for a grid header, unambiguous about which quarter it is.
function shortQuarter(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  const month = d.toLocaleString("en-GB", { month: "short" });
  return `${d.getDate()} ${month} ${String(d.getFullYear()).slice(2)}`;
}

function arrow(delta: number): { glyph: string; color: string } {
  // A flat band, because a 0.4-point move quarter to quarter is noise and an arrow claiming
  // direction for it would be worse than saying nothing.
  if (delta > 1) return { glyph: "▲", color: "#22c55e" };
  if (delta < -1) return { glyph: "▼", color: "#ef4444" };
  return { glyph: "▬", color: "#64748b" };
}

// The fundamental score for each trailing-twelve-month quarter, newest first.
//
// Shows the most recent few inline with their period-end dates and the move against the prior
// quarter; the full run (up to 20) is in the tooltip. An anonymous line tells you the shape but
// not which quarter turned - and "when did this start deteriorating" is the actual question.
export function ScoreHistoryCell(p: ICellRendererParams) {
  const row = p.data as
    | { score_history?: number[] | null; score_history_dates?: string[] | null }
    | undefined;
  const scores = (row?.score_history ?? []).filter((n): n is number => typeof n === "number");
  const dates = row?.score_history_dates ?? [];
  if (scores.length === 0) return <span className="text-slate-600">—</span>;

  // Stored oldest -> newest; read newest first, the way you would ask the question.
  const points = scores
    .map((score, i) => ({
      score,
      date: dates[i] ?? "",
      delta: i > 0 ? score - scores[i - 1] : 0,
    }))
    .reverse();

  const shown = points.slice(0, 4);
  const tooltip = points
    .map((q) => {
      const a = arrow(q.delta);
      return `${q.date ? shortQuarter(q.date) : "?"}   ${q.score.toFixed(0)}  ${a.glyph}`;
    })
    .join("
");

  return (
    <span className="flex items-center gap-2" title={`${points.length} quarters (TTM)

${tooltip}`}>
      {shown.map((q, i) => {
        const a = arrow(q.delta);
        return (
          <span key={i} className="flex flex-col items-center leading-tight">
            <span className="num text-[11px] font-semibold" style={{ color: scoreColor(q.score) }}>
              {q.score.toFixed(0)}
              <span style={{ color: a.color }} className="ml-0.5">{a.glyph}</span>
            </span>
            <span className="text-[9px] text-slate-500">
              {q.date ? shortQuarter(q.date) : "—"}
            </span>
          </span>
        );
      })}
      {points.length > shown.length && (
        <span className="text-[10px] text-slate-500">+{points.length - shown.length}</span>
      )}
    </span>
  );
}

function scoreColor(v: number): string {
  const hue = Math.max(0, Math.min(120, (v / 100) * 120));
  return `hsl(${hue}, 70%, 60%)`;
}
