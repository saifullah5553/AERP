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

// The fundamental score across its trailing-twelve-month history, drawn inline.
//
// A sparkline rather than a number because the arc is the point: a 70 climbing out of 40 and a
// 70 sliding down from 95 are different businesses, and no single figure separates them. Drawn
// as an SVG polyline - no chart library for a 200px cell.
export function ScoreHistoryCell(p: ICellRendererParams) {
  const raw = p.value as number[] | null | undefined;
  const pts = (raw ?? []).filter((n): n is number => typeof n === "number");
  if (pts.length < 2) return <span className="text-slate-600">—</span>;

  const W = 150;
  const H = 22;
  // Fixed 0-100 scale, never auto-fitted: autoscaling would make every company's history look
  // equally dramatic and hide that one sits at 30 while another sits at 90.
  const x = (i: number) => (i / (pts.length - 1)) * (W - 2) + 1;
  const y = (v: number) => H - 2 - (Math.max(0, Math.min(100, v)) / 100) * (H - 4);
  const path = pts.map((v, i) => `${x(i).toFixed(1)},${y(v).toFixed(1)}`).join(" ");

  const first = pts[0];
  const last = pts[pts.length - 1];
  const delta = last - first;
  const stroke = delta > 5 ? "#22c55e" : delta < -5 ? "#ef4444" : "#94a3b8";

  return (
    <span
      className="flex items-center gap-2"
      title={`${pts.length} quarterly TTM points, oldest to newest: ${first.toFixed(0)} → ${last.toFixed(0)}`}
    >
      <svg width={W} height={H} className="shrink-0" aria-hidden>
        <line x1={1} y1={y(50)} x2={W - 1} y2={y(50)} stroke="#334155" strokeWidth={0.5} />
        <polyline
          points={path}
          fill="none"
          stroke={stroke}
          strokeWidth={1.5}
          strokeLinejoin="round"
          strokeLinecap="round"
        />
        <circle cx={x(pts.length - 1)} cy={y(last)} r={2} fill={stroke} />
      </svg>
      <span className="num text-[11px] text-slate-400">{pts.length}q</span>
    </span>
  );
}
