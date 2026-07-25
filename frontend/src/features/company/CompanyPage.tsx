import { type ReactNode, useEffect, useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";

import { api } from "@/lib/api";
import { fmtChangePct, fmtCompact, fmtNumber, fmtPercent, titleize } from "@/lib/format";
import { openQuoteStream } from "@/lib/liveQuotes";
import {
  type CheckItem,
  type Condition,
  investmentChecklist,
  investmentGrade,
  type Level,
  latestCashFlow,
  marketCondition,
  num,
  patternRead,
  type RiskItem,
  riskAnalysis,
  scoreSet,
  strengthLabel,
  technicalRead,
} from "@/lib/research";
import {
  commoditySummary,
  companyMaterials,
  type MaterialImpact,
  type RawMaterialsData,
} from "@/lib/rawMaterials";
import type { MarketPulse } from "@/types/api";
import type { CompanyDetail, Row } from "@/types/company";
import PeersTable from "./PeersTable";
import ScoreHistoryChart from "./ScoreHistoryChart";
import StatementsTable, {
  BALANCE_FIELDS,
  CASHFLOW_FIELDS,
  INCOME_FIELDS,
} from "./StatementsTable";

// ── Shared tone maps ─────────────────────────────────────────────────────────
const CONDITION_TONE: Record<Condition, string> = {
  Bullish: "#22c55e",
  Bearish: "#ef4444",
  Neutral: "#94a3b8",
};
const LEVEL_TONE: Record<Level, string> = {
  Low: "#22c55e",
  Medium: "#f59e0b",
  High: "#ef4444",
  Unknown: "#64748b",
};
const IMPACT_TONE: Record<string, string> = {
  Positive: "#22c55e",
  Neutral: "#94a3b8",
  Negative: "#ef4444",
};
const TREND_ARROW: Record<string, string> = { increasing: "↑", decreasing: "↓", sideways: "→" };
const GRADE_TONE = (g: string) =>
  g.startsWith("A") ? "#22c55e" : g.startsWith("B") ? "#eab308" : g === "—" ? "#64748b" : "#f87171";

type Tab = "income" | "balance" | "cashflow" | "technicals" | "patterns" | "valuation";
const TABS: { id: Tab; label: string }[] = [
  { id: "valuation", label: "Valuation" },
  { id: "income", label: "Income" },
  { id: "balance", label: "Balance" },
  { id: "cashflow", label: "Cash Flow" },
  { id: "technicals", label: "Technicals" },
  { id: "patterns", label: "Patterns" },
];

// ── Small presentational primitives ──────────────────────────────────────────
function Card({ title, children, right }: { title: string; children: ReactNode; right?: ReactNode }) {
  return (
    <section className="rounded-lg border border-base-600 bg-base-800">
      <div className="flex items-center justify-between border-b border-base-600 px-4 py-2.5">
        <h3 className="text-xs font-semibold uppercase tracking-wide text-slate-400">{title}</h3>
        {right}
      </div>
      {children}
    </section>
  );
}

function Pill({ text, color }: { text: string; color: string }) {
  return (
    <span
      className="rounded px-2 py-0.5 text-xs font-semibold"
      style={{ background: `${color}22`, color }}
    >
      {text}
    </span>
  );
}

function StatRow({ label, value, tone }: { label: string; value: string; tone?: string }) {
  return (
    <div className="flex items-center justify-between border-b border-base-700/40 py-1.5">
      <span className="text-xs text-slate-400">{label}</span>
      <span className="num text-sm font-medium" style={{ color: tone ?? "#e2e8f0" }}>
        {value}
      </span>
    </div>
  );
}

function ScoreChip({ label, value }: { label: string; value: number | null }) {
  const v = value == null ? null : Math.round(value);
  const tone = v == null ? "#64748b" : v >= 60 ? "#22c55e" : v >= 45 ? "#eab308" : "#f87171";
  return (
    <div className="flex flex-col items-center rounded border border-base-600 bg-base-900 px-3 py-1.5">
      <span className="num text-lg font-bold" style={{ color: tone }}>{v ?? "—"}</span>
      <span className="text-[10px] uppercase tracking-wide text-slate-500">{label}</span>
    </div>
  );
}

// ── Metric grids for the tabbed raw-financials section (unchanged data) ───────
type Fmt = "num" | "pct" | "compact";
function metricValue(row: Row | null, key: string, fmt: Fmt): string {
  const v = num(row?.[key]);
  if (v == null) return "—";
  if (fmt === "pct") return fmtPercent(v);
  if (fmt === "compact") return fmtCompact(v);
  return fmtNumber(v);
}
function MetricGrid({ row, items }: { row: Row | null; items: [string, string, Fmt][] }) {
  return (
    <div className="grid grid-cols-2 gap-x-8 gap-y-1.5 p-4 md:grid-cols-3">
      {items.map(([key, label, fmt]) => (
        <div key={key} className="flex items-center justify-between border-b border-base-700/40 py-1">
          <span className="text-xs text-slate-400">{label}</span>
          <span className="num text-sm text-slate-200">{metricValue(row, key, fmt)}</span>
        </div>
      ))}
    </div>
  );
}
const VALUATION: [string, string, Fmt][] = [
  ["pe_ratio", "P/E", "num"], ["peg_ratio", "PEG", "num"], ["price_to_sales", "P/S", "num"],
  ["price_to_book", "P/B", "num"], ["ev_to_ebitda", "EV/EBITDA", "num"],
  ["enterprise_value", "Enterprise Value", "compact"], ["book_value_per_share", "Book Value/Sh", "num"],
  ["altman_z", "Altman Z", "num"], ["piotroski_f", "Piotroski F", "num"],
  ["dividend_yield", "Div Yield", "pct"],
];
const TECHNICALS: [string, string, Fmt][] = [
  ["rsi_14", "RSI(14)", "num"], ["macd", "MACD", "num"], ["macd_signal", "MACD Signal", "num"],
  ["adx_14", "ADX(14)", "num"], ["atr_14", "ATR(14)", "num"], ["sma_50", "SMA 50", "num"],
  ["sma_200", "SMA 200", "num"], ["ema_50", "EMA 50", "num"], ["supertrend", "SuperTrend", "num"],
  ["vwap", "VWAP", "num"], ["mfi_14", "MFI(14)", "num"], ["bb_upper", "Boll Upper", "num"],
  ["bb_lower", "Boll Lower", "num"], ["high_52w", "52w High", "num"], ["low_52w", "52w Low", "num"],
  ["pct_from_52w_high", "From 52w High", "pct"], ["momentum", "Momentum", "pct"],
  ["volatility", "Volatility", "pct"], ["trend_strength", "Trend Strength", "num"],
];

function growthOf(rows: Row[], key: string): number | null {
  const a = num(rows[rows.length - 1]?.[key]);
  const b = num(rows[rows.length - 2]?.[key]);
  if (a == null || b == null || b === 0) return null;
  return (a - b) / Math.abs(b);
}

// ── Page ─────────────────────────────────────────────────────────────────────
export default function CompanyPage() {
  const { symbol = "" } = useParams();
  const [data, setData] = useState<CompanyDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [tab, setTab] = useState<Tab>("income");
  const [pulse, setPulse] = useState<MarketPulse[]>([]);
  const [rawMaterials, setRawMaterials] = useState<RawMaterialsData | null>(null);

  useEffect(() => {
    const ctrl = new AbortController();
    setData(null);
    setError(null);
    api
      .company(symbol, ctrl.signal)
      .then(setData)
      .catch((e: unknown) => {
        if (!ctrl.signal.aborted) setError(e instanceof Error ? e.message : "Failed to load");
      });
    return () => ctrl.abort();
  }, [symbol]);

  // Market pulse + raw-material trends (shared, small; load once).
  useEffect(() => {
    const ctrl = new AbortController();
    api.pulse(ctrl.signal).then(setPulse).catch(() => setPulse([]));
    api.rawMaterials(ctrl.signal).then(setRawMaterials).catch(() => setRawMaterials(null));
    return () => ctrl.abort();
  }, []);

  useEffect(() => {
    if (!symbol) return;
    return openQuoteStream({
      symbols: [symbol],
      onQuote: (q) => {
        if (q.symbol !== symbol) return;
        setData((prev) =>
          prev
            ? { ...prev, quote: { ...(prev.quote ?? {}), price: q.price, change_pct: q.change_pct } }
            : prev,
        );
      },
    });
  }, [symbol]);

  const derived = useMemo(() => {
    if (!data) return null;
    const sec = data.security as Row;
    const scores = scoreSet(data);
    const tech = technicalRead(data);
    const cf = latestCashFlow(data);
    const materials = companyMaterials(
      (sec.sector as string) ?? null,
      (sec.industry as string) ?? null,
      rawMaterials,
    );
    const commodity = commoditySummary(materials);
    const region = String(sec.region ?? "");
    const regionCondition: Condition = ((): Condition => {
      const p = pulse.find((x) => x.region === region);
      if (!p) return "Neutral";
      return p.pulse === "bullish" ? "Bullish" : p.pulse === "bearish" ? "Bearish" : "Neutral";
    })();
    return {
      scores,
      tech,
      cf,
      materials,
      commodity,
      regionCondition,
      grade: investmentGrade(scores.overall),
      condition: marketCondition(scores.overall),
      fundStrength: strengthLabel(scores.fundamental),
      patternSignal: patternRead(data),
      risks: riskAnalysis(data, { regionCondition, commodity }),
      checklist: investmentChecklist(data, { tech, regionCondition, commodity, fcf: cf.fcf }),
      netProfitGrowth: growthOf(data.statements.income, "net_income"),
    };
  }, [data, pulse, rawMaterials]);

  const changePct = useMemo(() => num(data?.quote?.change_pct), [data]);

  if (error) return <Centered>Could not load {symbol}: {error}</Centered>;
  if (!data || !derived) return <Centered>Loading {symbol}…</Centered>;

  const sec = data.security as Row;
  const price = num(data.quote?.price);
  const { scores, grade, condition } = derived;

  return (
    <div className="h-full overflow-y-auto bg-base-900 text-slate-200">
      {/* Header */}
      <header className="sticky top-0 z-10 border-b border-base-600 bg-base-900/95 px-5 py-3 backdrop-blur">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex items-center gap-4">
            <Link to="/" className="text-sm text-slate-400 hover:text-accent">← Research</Link>
            <div>
              <div className="flex items-center gap-2">
                <span className="text-xl font-bold text-accent">{data.security.symbol}</span>
                <span className="rounded bg-base-700 px-1.5 py-0.5 text-[10px] text-slate-400">
                  {data.security.market_code}
                </span>
                <Pill text={condition} color={CONDITION_TONE[condition]} />
              </div>
              <div className="text-sm text-slate-300">{String(sec.name ?? "")}</div>
              <div className="mt-0.5 text-[11px] text-slate-500">
                {[sec.sector, sec.industry].filter(Boolean).join(" · ") || "—"}
              </div>
            </div>
          </div>
          <div className="flex items-center gap-4">
            <div className="text-right">
              <div className="num text-lg font-semibold">{fmtNumber(price)}</div>
              <div className="num text-sm" style={{ color: CONDITION_TONE[changePct != null && changePct > 0 ? "Bullish" : changePct != null && changePct < 0 ? "Bearish" : "Neutral"] }}>
                {fmtChangePct(changePct)}
              </div>
            </div>
            <div className="flex flex-col items-center rounded-lg border px-3 py-1" style={{ borderColor: GRADE_TONE(grade) }}>
              <span className="text-2xl font-black leading-none" style={{ color: GRADE_TONE(grade) }}>{grade}</span>
              <span className="text-[9px] uppercase tracking-wide text-slate-500">Grade</span>
            </div>
          </div>
        </div>
        {/* AI research score band */}
        <div className="mt-3 flex flex-wrap gap-2">
          <ScoreChip label="Overall" value={scores.overall} />
          <ScoreChip label="Fundamental" value={scores.fundamental} />
          <ScoreChip label="Technical" value={scores.technical} />
          <ScoreChip label="Quality" value={scores.quality} />
          <ScoreChip label="Risk" value={scores.risk} />
        </div>
      </header>

      {/* Body */}
      <div className="grid gap-4 p-4 lg:grid-cols-3">
        <div className="space-y-4 lg:col-span-2">
          <FundamentalSection detail={data} derived={derived} />
          <TechnicalSection tech={derived.tech} patternSignal={derived.patternSignal} />
          <RawMaterialSection materials={derived.materials} outlook={rawMaterials?.outlook ?? null} />
          <RiskSection risks={derived.risks} />

          {/* Detailed financials (existing tabs, unchanged data source) */}
          <Card title="Financial Statements & Indicators">
            <div className="flex flex-wrap border-b border-base-600">
              {TABS.map((t) => (
                <button
                  key={t.id}
                  onClick={() => setTab(t.id)}
                  className={`px-4 py-2 text-sm font-medium ${
                    tab === t.id ? "border-b-2 border-accent text-accent" : "text-slate-400 hover:text-slate-200"
                  }`}
                >
                  {t.label}
                </button>
              ))}
            </div>
            {tab === "valuation" && <MetricGrid row={data.ratios} items={VALUATION} />}
            {tab === "income" && <StatementsTable rows={data.statements.income} fields={INCOME_FIELDS} />}
            {tab === "balance" && <StatementsTable rows={data.statements.balance} fields={BALANCE_FIELDS} />}
            {tab === "cashflow" && <StatementsTable rows={data.statements.cashflow} fields={CASHFLOW_FIELDS} />}
            {tab === "technicals" && <MetricGrid row={data.technical} items={TECHNICALS} />}
            {tab === "patterns" && <PatternsList patterns={data.patterns} />}
          </Card>
        </div>

        <div className="space-y-4">
          <Card title="AI Research Summary">
            <p className="p-4 text-sm leading-relaxed text-slate-300">{data.ai_summary}</p>
          </Card>
          <ChecklistSection items={derived.checklist} />
          <InsiderCard summary={data.insider_summary} transactions={data.insider} />
          <PeersTable peers={data.peers} />
          <NewsCard news={data.news} />
          <ScoreHistoryChart history={data.score_history} />
        </div>
      </div>
    </div>
  );
}

// ── Fundamental analysis ─────────────────────────────────────────────────────
function FundamentalSection({
  detail,
  derived,
}: {
  detail: CompanyDetail;
  derived: { fundStrength: string; cf: { fcf: number | null; trend: string }; netProfitGrowth: number | null };
}) {
  const r = detail.ratios ?? {};
  const strengthColor =
    derived.fundStrength === "Strong" ? "#22c55e" : derived.fundStrength === "Average" ? "#eab308" : "#f87171";
  const pct = (k: string) => (num(r[k]) == null ? "—" : fmtPercent(num(r[k]) as number));
  const rows: [string, string, string?][] = [
    ["Revenue Growth (TTM)", pct("revenue_growth")],
    ["EPS Growth", pct("eps_growth")],
    ["Net Profit Growth", derived.netProfitGrowth == null ? "—" : fmtPercent(derived.netProfitGrowth)],
    ["Operating Margin", pct("operating_margin")],
    ["Net Margin", pct("net_margin")],
    ["ROE", pct("roe")],
    ["ROIC", pct("roic")],
    ["Debt / Equity", num(r.debt_to_equity) == null ? "—" : fmtNumber(num(r.debt_to_equity))],
    ["Interest Coverage", num(r.interest_coverage) == null ? "—" : fmtNumber(num(r.interest_coverage))],
    ["Free Cash Flow", derived.cf.fcf == null ? "—" : fmtCompact(derived.cf.fcf)],
    ["Cash Flow Trend", derived.cf.trend],
  ];
  return (
    <Card
      title="Fundamental Analysis"
      right={<Pill text={`${derived.fundStrength} Fundamentals`} color={strengthColor} />}
    >
      <div className="grid grid-cols-1 gap-x-8 px-4 py-2 md:grid-cols-2">
        {rows.map(([label, value]) => (
          <StatRow key={label} label={label} value={value} />
        ))}
      </div>
    </Card>
  );
}

// ── Technical analysis (chart-free) ──────────────────────────────────────────
function TechnicalSection({
  tech,
  patternSignal,
}: {
  tech: ReturnType<typeof technicalRead>;
  patternSignal: string | null;
}) {
  const trendTone = tech.trend === "Bullish" ? "#22c55e" : tech.trend === "Bearish" ? "#ef4444" : "#94a3b8";
  const rsiTone = tech.rsiCondition === "Overbought" ? "#ef4444" : tech.rsiCondition === "Oversold" ? "#22c55e" : "#94a3b8";
  const yesNo = (b: boolean | null) => (b == null ? "—" : b ? "Yes" : "No");
  const yesTone = (b: boolean | null) => (b == null ? "#94a3b8" : b ? "#22c55e" : "#ef4444");
  return (
    <Card title="Technical Analysis">
      <div className="grid grid-cols-1 gap-x-8 px-4 py-2 md:grid-cols-2">
        <StatRow label="Trend" value={tech.trend} tone={trendTone} />
        <StatRow label="Momentum" value={tech.momentum} tone={tech.momentum === "Strong" ? "#22c55e" : "#f59e0b"} />
        <StatRow label="Above 50 DMA" value={yesNo(tech.aboveSma50)} tone={yesTone(tech.aboveSma50)} />
        <StatRow label="Above 200 DMA" value={yesNo(tech.aboveSma200)} tone={yesTone(tech.aboveSma200)} />
        <StatRow
          label="RSI Condition"
          value={tech.rsi != null ? `${tech.rsiCondition} (${tech.rsi.toFixed(0)})` : tech.rsiCondition}
          tone={rsiTone}
        />
        <StatRow label="Volume" value={tech.volume} />
        <StatRow label="Pattern Read" value={patternSignal ?? "—"} />
        <StatRow label="Detected Pattern" value={tech.pattern ? titleize(tech.pattern) : "—"} />
      </div>
    </Card>
  );
}

// ── Raw material cost trend ──────────────────────────────────────────────────
function RawMaterialSection({
  materials,
  outlook,
}: {
  materials: MaterialImpact[];
  outlook: string | null;
}) {
  return (
    <Card title="Major Raw Material Price Trend & Margin Impact">
      {materials.length === 0 ? (
        <p className="p-4 text-sm text-slate-500">
          No major tracked commodity inputs map to this sector — margins are driven mainly
          by non-commodity factors.
        </p>
      ) : (
        <div className="divide-y divide-base-700/40">
          {materials.map((m) => (
            <div key={m.symbol} className="flex flex-wrap items-center justify-between gap-2 px-4 py-2.5">
              <div>
                <div className="text-sm font-medium text-slate-200">
                  {TREND_ARROW[m.trend]} {m.name}
                  <span className="ml-2 text-xs capitalize text-slate-500">{m.trend}</span>
                </div>
                <div className="text-[11px] text-slate-500">{m.effect}</div>
              </div>
              <Pill text={`${m.impact} Impact`} color={IMPACT_TONE[m.impact]} />
            </div>
          ))}
        </div>
      )}
      {outlook && (
        <div className="border-t border-base-700/50 px-4 py-2.5">
          <div className="mb-1 text-[11px] font-semibold uppercase tracking-wide text-slate-500">
            Raw Material Cost Outlook
          </div>
          <p className="text-sm leading-relaxed text-slate-300">{outlook}</p>
        </div>
      )}
    </Card>
  );
}

// ── Risk analysis ────────────────────────────────────────────────────────────
function RiskSection({ risks }: { risks: RiskItem[] }) {
  return (
    <Card title="Risk Analysis">
      <div className="grid grid-cols-1 gap-x-8 px-4 py-2 sm:grid-cols-2 lg:grid-cols-3">
        {risks.map((r) => (
          <div key={r.name} className="flex items-center justify-between border-b border-base-700/40 py-2">
            <div>
              <div className="text-sm text-slate-300">{r.name}</div>
              <div className="text-[10px] text-slate-500">{r.note}</div>
            </div>
            <Pill text={r.level} color={LEVEL_TONE[r.level]} />
          </div>
        ))}
      </div>
    </Card>
  );
}

// ── Investment checklist ─────────────────────────────────────────────────────
function ChecklistSection({ items }: { items: CheckItem[] }) {
  const passed = items.filter((i) => i.pass).length;
  return (
    <Card title="Investment Checklist" right={<span className="num text-xs text-slate-400">{passed}/{items.length}</span>}>
      <div className="p-3">
        {items.map((i) => (
          <div key={i.label} className="flex items-center gap-2 py-1 text-sm">
            <span style={{ color: i.pass ? "#22c55e" : "#64748b" }}>{i.pass ? "✓" : "○"}</span>
            <span className={i.pass ? "text-slate-200" : "text-slate-500"}>{i.label}</span>
          </div>
        ))}
      </div>
    </Card>
  );
}

// ── Patterns (kept; grouped candlestick/chart/harmonic) ──────────────────────
function PatternRow({ p }: { p: Row }) {
  const dir = String(p.direction ?? "");
  const color = dir === "bullish" ? "#22c55e" : dir === "bearish" ? "#ef4444" : "#94a3b8";
  const conf = num(p.confidence) ?? 0;
  return (
    <div className="flex items-center justify-between rounded border border-base-700 bg-base-900 px-3 py-2">
      <div>
        <span className="font-medium text-slate-200">{titleize(String(p.name))}</span>
        <span className="ml-2 text-xs uppercase" style={{ color }}>{dir}</span>
      </div>
      <div className="flex items-center gap-4 text-xs text-slate-400">
        {num(p.target_price) != null && <span>Target {fmtNumber(num(p.target_price))}</span>}
        <span className="num">conf {(conf * 100).toFixed(0)}%</span>
      </div>
    </div>
  );
}
function PatternsList({ patterns }: { patterns: Row[] }) {
  if (patterns.length === 0)
    return <div className="p-4 text-sm text-slate-500">No active patterns detected.</div>;
  const candles = patterns.filter((p) => String(p.category) === "candlestick");
  const charts = patterns.filter((p) => String(p.category) === "chart");
  const others = patterns.filter(
    (p) => String(p.category) !== "candlestick" && String(p.category) !== "chart",
  );
  const section = (title: string, rows: Row[]) =>
    rows.length > 0 && (
      <div className="space-y-2">
        <h4 className="text-xs font-semibold uppercase tracking-wide text-slate-500">{title}</h4>
        {rows.map((p, i) => <PatternRow key={i} p={p} />)}
      </div>
    );
  return (
    <div className="space-y-4 p-4">
      {section("Candlestick Patterns", candles)}
      {section("Chart Patterns", charts)}
      {section("Harmonic Patterns", others)}
    </div>
  );
}

const INSIDER_COLOR: Record<string, string> = {
  strong_buying: "#22c55e", buying: "#4ade80", neutral: "#94a3b8",
  selling: "#f87171", strong_selling: "#ef4444", no_activity: "#64748b",
};
function InsiderCard({ summary, transactions }: { summary: Row | null; transactions: Row[] }) {
  const activity = typeof summary?.activity === "string" ? summary.activity : "no_activity";
  const score = num(summary?.score);
  const buy = num(summary?.buy_count) ?? 0;
  const sell = num(summary?.sell_count) ?? 0;
  const window = num(summary?.window_days) ?? 60;
  const color = INSIDER_COLOR[activity] ?? "#94a3b8";
  const recent = (transactions ?? []).slice(0, 6);
  if (activity === "no_activity" && recent.length === 0) return null;
  return (
    <Card title={`Insider Activity (${window}d)`} right={score !== null ? <span className="num text-sm font-semibold" style={{ color }}>{score.toFixed(0)}/100</span> : undefined}>
      <div className="p-4">
        <div className="text-sm font-medium" style={{ color }}>{titleize(activity)}</div>
        {(buy > 0 || sell > 0) && (
          <div className="mt-1 text-xs text-slate-400">{buy} buying · {sell} selling</div>
        )}
        {recent.length > 0 && (
          <div className="mt-3 space-y-1 border-t border-base-700/50 pt-2">
            {recent.map((t, i) => {
              const isBuy = String(t.transaction_type ?? "").toLowerCase() === "buy";
              return (
                <div key={i} className="flex items-center justify-between text-xs">
                  <span className="truncate text-slate-400" title={String(t.insider_name ?? "")}>
                    {String(t.insider_name ?? "—").slice(0, 22)}
                  </span>
                  <span className="num" style={{ color: isBuy ? "#22c55e" : "#ef4444" }}>
                    {isBuy ? "BUY" : "SELL"} {fmtCompact(num(t.shares))}
                  </span>
                </div>
              );
            })}
          </div>
        )}
      </div>
    </Card>
  );
}

function NewsCard({ news }: { news: Row[] }) {
  if (!news || news.length === 0) return null;
  return (
    <Card title="Latest News">
      <div className="divide-y divide-base-700/40">
        {news.slice(0, 6).map((n, i) => (
          <a
            key={i}
            href={typeof n.url === "string" ? n.url : undefined}
            target="_blank"
            rel="noreferrer"
            className="block px-4 py-2 hover:bg-base-700/40"
          >
            <div className="text-sm text-slate-200">{typeof n.title === "string" ? n.title : ""}</div>
            <div className="mt-0.5 text-[11px] text-slate-500">
              {typeof n.source === "string" ? n.source : ""}
              {typeof n.published_at === "string" ? ` · ${n.published_at.slice(0, 10)}` : ""}
            </div>
          </a>
        ))}
      </div>
    </Card>
  );
}

function Centered({ children }: { children: ReactNode }) {
  return (
    <div className="flex h-full items-center justify-center bg-base-900 text-slate-400">{children}</div>
  );
}
