import { type ReactNode, useEffect, useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";

import { api, type CotData } from "@/lib/api";
import {
  fmtChangePct,
  fmtCompact,
  fmtNumber,
  fmtPercent,
  fmtSnapshotAge,
  fmtSnapshotDate,
  titleize,
} from "@/lib/format";
import { openQuoteStream } from "@/lib/liveQuotes";
import {
  type CheckItem,
  businessCycle,
  type Condition,
  investmentChecklist,
  investmentGrade,
  isFinancial,
  type Level,
  latestCashFlow,
  type MacroFactor,
  macroSensitivity,
  marketCondition,
  num,
  patternRead,
  type RiskItem,
  riskAnalysis,
  scoreSet,
  strengthLabel,
  technicalRead,
  wyckoffPhase,
} from "@/lib/research";
import {
  commoditySummary,
  companyMaterials,
  type MaterialImpact,
  type RawMaterialsData,
} from "@/lib/rawMaterials";
import { confidenceTone, dataSources } from "@/lib/provenance";
import type {
  CatalystsData,
  CountryRegime,
  MacroRegimeData,
  MarketPulse,
  SectorStat,
  SectorStatsData,
  SnapshotMeta,
} from "@/types/api";
import type { CompanyDetail, Row } from "@/types/company";
import PabraiRadar from "./PabraiRadar";
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
const IMPACT_TONE: Record<string, string> = {
  Positive: "#22c55e", Neutral: "#94a3b8", Negative: "#ef4444",
};
const TREND_ARROW: Record<string, string> = { increasing: "↑", decreasing: "↓", sideways: "→" };
const LEVEL_TONE: Record<Level, string> = {
  Low: "#22c55e",
  Medium: "#f59e0b",
  High: "#ef4444",
  Unknown: "#64748b",
};
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
      <span className="num text-sm font-medium" style={{ color: tone ?? "var(--app-fg)" }}>
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
  // Statements are newest-first: [0] latest, [1] prior period.
  const a = num(rows[0]?.[key]);
  const b = num(rows[1]?.[key]);
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
  const [sectorStats, setSectorStats] = useState<SectorStatsData | null>(null);
  const [regime, setRegime] = useState<MacroRegimeData | null>(null);
  const [catalysts, setCatalysts] = useState<CatalystsData | null>(null);
  const [meta, setMeta] = useState<SnapshotMeta | null>(null);
  const [cot, setCot] = useState<Record<string, CotData>>({});

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
    api.sectorStats(ctrl.signal).then(setSectorStats).catch(() => setSectorStats(null));
    api.regime(ctrl.signal).then(setRegime).catch(() => setRegime(null));
    api.catalysts(ctrl.signal).then(setCatalysts).catch(() => setCatalysts(null));
    api.meta(ctrl.signal).then(setMeta).catch(() => setMeta(null));
    api.cot(ctrl.signal).then(setCot).catch(() => setCot({}));
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
    const regionRegime: CountryRegime | undefined = regime?.countries?.[region];
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
      macroFactors: macroSensitivity((sec.sector as string) ?? null, (sec.industry as string) ?? null, regionRegime),
      cycle: businessCycle(data),
      wyckoff: wyckoffPhase(data),
    };
  }, [data, pulse, rawMaterials, regime]);

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
            <div className="flex flex-col">
              <Link to="/" className="text-sm text-slate-400 hover:text-accent">← Research</Link>
              {meta?.generated_at && (
                <span
                  className="text-[10px] text-slate-600"
                  title={`Snapshot generated ${fmtSnapshotDate(meta.generated_at)}`}
                >
                  Data {fmtSnapshotAge(meta.generated_at)}
                </span>
              )}
            </div>
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
          <SignalCard signal={data.signal} />
          <CotSection data={cot[String(sec.provider_symbol ?? "")]} />
          <BusinessOverview summary={typeof sec.long_business_summary === "string" ? sec.long_business_summary : null} />
          <PabraiSection scores={data.scores} />
          <FundamentalSection detail={data} derived={derived} />
          <ValuationSection detail={data} />
          <SectorComparison detail={data} sectorStats={sectorStats} />
          <TechnicalSection tech={derived.tech} patternSignal={derived.patternSignal} wyckoff={derived.wyckoff} />
          <MacroSensitivitySection factors={derived.macroFactors} cycle={derived.cycle} />
          <RawMaterialSection materials={derived.materials} outlook={rawMaterials?.outlook ?? null} />
          <CatalystSection sec={data.security as Row} catalysts={catalysts} materials={derived.materials} />
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
            <p className="p-4 text-sm leading-relaxed text-slate-300">
              {/* Strip any legacy buy/sell/hold signal clause — research only. */}
              {data.ai_summary.replace(/\s*Current signal:[^.]*\.\s*/i, " ").trim()}
            </p>
          </Card>
          <EstimatesSection sec={data.security as Row} />
          <ChecklistSection items={derived.checklist} />
          <InsiderCard summary={data.insider_summary} transactions={data.insider} />
          <PeersTable peers={data.peers} />
          <NewsCard news={data.news} />
          <ScoreHistoryChart history={data.score_history} />
          <DataSourcesCard
            region={String(sec.region ?? "")}
            assetClass={String(sec.asset_class ?? "equity")}
            meta={meta}
          />
        </div>
      </div>
    </div>
  );
}

// ── Model signal (labeled, not advice) — date generated + return since ───────
// Single semantic colour per signal so the card reads correctly on both themes
// (light tint background + solid label chip with white text).
const SIGNAL_TONE: Record<string, { color: string; label: string }> = {
  strong_buy: { color: "#16a34a", label: "Strong Buy" },
  buy: { color: "#22c55e", label: "Buy" },
  hold: { color: "#64748b", label: "Hold" },
  sell: { color: "#ef4444", label: "Sell" },
  strong_sell: { color: "#b91c1c", label: "Strong Sell" },
};

function SignalCard({ signal }: { signal: Row | null }) {
  if (!signal) return null;
  const type = String(signal.signal_type ?? signal.signal ?? "");
  const tone = SIGNAL_TONE[type];
  if (!tone) return null;
  const since = typeof signal.signal_since === "string" ? signal.signal_since.slice(0, 10) : null;
  const ret = num(signal.signal_return_pct);
  const retTone = ret == null ? "#94a3b8" : ret > 0 ? "#22c55e" : ret < 0 ? "#ef4444" : "#94a3b8";
  const conf = num(signal.confidence);
  return (
    <section className="overflow-hidden rounded-lg border border-base-600 bg-base-800">
      <div className="flex flex-wrap items-center gap-x-6 gap-y-3 p-4" style={{ background: `${tone.color}1f` }}>
        <div className="flex flex-col">
          <span className="text-[10px] uppercase tracking-widest text-slate-500">Model Signal</span>
          <span className="rounded px-3 py-1 text-lg font-black text-white" style={{ background: tone.color }}>
            {tone.label}
          </span>
        </div>
        {since && (
          <div className="flex flex-col">
            <span className="text-[10px] uppercase tracking-widest text-slate-500">Generated</span>
            <span className="num text-sm font-semibold" style={{ color: "var(--app-fg)" }}>{since}</span>
          </div>
        )}
        {ret != null && (
          <div className="flex flex-col">
            <span className="text-[10px] uppercase tracking-widest text-slate-500">Return Since</span>
            <span className="num text-lg font-black" style={{ color: retTone }}>
              {ret > 0 ? "+" : ""}{ret.toFixed(2)}%
            </span>
          </div>
        )}
        {conf != null && (
          <div className="flex flex-col">
            <span className="text-[10px] uppercase tracking-widest text-slate-500">Confidence</span>
            <span className="num text-sm font-semibold" style={{ color: "var(--app-fg)" }}>{Math.round(conf * 100)}%</span>
          </div>
        )}
      </div>
      <div className="border-t border-base-700/50 px-4 py-1.5 text-[10px] text-slate-500">
        Model-derived, rule-based · not investment advice. Return since is the price move from the
        signal date, not a forecast.
      </div>
    </section>
  );
}

// ── Commitment of Traders (CFTC) — non-commercial "smart money" positioning ──
function CotSection({ data }: { data: CotData | undefined }) {
  if (!data) return null;
  const stanceTone = data.stance === "Net Long" ? "#22c55e" : data.stance === "Net Short" ? "#ef4444" : "#94a3b8";
  const flowTone = data.flow === "Buying" ? "#22c55e" : data.flow === "Selling" ? "#ef4444" : "#94a3b8";
  const pl = data.pct_long ?? 50;
  const cell = (label: string, value: string, tone?: string) => (
    <div className="flex flex-col">
      <span className="text-[10px] uppercase tracking-widest text-slate-500">{label}</span>
      <span className="num text-sm font-bold" style={{ color: tone ?? "var(--app-fg)" }}>{value}</span>
    </div>
  );
  return (
    <Card
      title="Commitment of Traders — Smart Money"
      right={<span className="text-[10px] text-slate-500">CFTC · {data.report_date}</span>}
    >
      <div className="grid grid-cols-2 gap-x-8 gap-y-3 px-4 py-3 md:grid-cols-4">
        {cell("Non-Comm Stance", data.stance, stanceTone)}
        {cell("This Week", `${data.flow} ${data.net_trend === "increasing" ? "↑" : data.net_trend === "decreasing" ? "↓" : ""}`, flowTone)}
        {cell("Net Position", data.net.toLocaleString(), stanceTone)}
        {cell("Open Interest", `${data.oi?.toLocaleString() ?? "—"} ${data.oi_trend === "increasing" ? "↑" : data.oi_trend === "decreasing" ? "↓" : ""}`)}
      </div>
      <div className="px-4 pb-3">
        <div className="mb-1 flex justify-between text-[10px] text-slate-500">
          <span>Speculators long {pl}%</span>
          <span>short {(100 - pl).toFixed(1)}%</span>
        </div>
        <div className="flex h-2.5 w-full overflow-hidden rounded-full bg-base-900">
          <span style={{ width: `${pl}%`, background: "#22c55e" }} />
          <span style={{ width: `${100 - pl}%`, background: "#ef4444" }} />
        </div>
      </div>
      <div className="border-t border-base-700/50 px-4 py-1.5 text-[10px] leading-relaxed text-slate-500">
        {data.contract} · non-commercials (large speculators) from the CFTC weekly report.
        "{data.flow}" = their net position {data.net_trend} vs last week. Data, not advice.
      </div>
    </Card>
  );
}

// ── Business overview (Yahoo longBusinessSummary; non-PSX) ───────────────────
function BusinessOverview({ summary }: { summary: string | null }) {
  if (!summary) return null;
  if (summary.length <= 420) {
    return (
      <Card title="Business Overview">
        <p className="px-4 py-3 text-sm leading-relaxed text-slate-300">{summary}</p>
      </Card>
    );
  }
  return (
    <Card title="Business Overview">
      <details className="group px-4 py-3">
        <summary className="cursor-pointer list-none text-sm leading-relaxed text-slate-300">
          <span className="group-open:hidden">
            {summary.slice(0, 420).trimEnd()}…{" "}
            <span className="text-xs font-medium text-accent">Show more</span>
          </span>
          <span className="hidden group-open:inline">
            {summary}{" "}
            <span className="text-xs font-medium text-accent">Show less</span>
          </span>
        </summary>
      </details>
    </Card>
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
  const sec = detail.security as Row;
  const fin = isFinancial((sec.sector as string) ?? null, (sec.industry as string) ?? null);
  const strengthColor =
    derived.fundStrength === "Strong" ? "#22c55e" : derived.fundStrength === "Average" ? "#eab308" : "#f87171";
  const pct = (k: string) => (num(r[k]) == null ? "—" : fmtPercent(num(r[k]) as number));
  // FCF is not a meaningful metric for banks/insurers/brokerages.
  const fcfVal = fin ? "N/A (financials)" : derived.cf.fcf == null ? "—" : fmtCompact(derived.cf.fcf);
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
    ["Free Cash Flow", fcfVal],
    ["Cash Flow Trend", fin ? "N/A (financials)" : derived.cf.trend],
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
  wyckoff,
}: {
  tech: ReturnType<typeof technicalRead>;
  patternSignal: string | null;
  wyckoff: { phase: string; note: string } | null;
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
        <StatRow label="Wyckoff Phase" value={wyckoff?.phase ?? "—"} />
      </div>
      {wyckoff && (
        <div className="border-t border-base-700/50 px-4 py-2 text-[11px] text-slate-500">{wyckoff.note}</div>
      )}
    </Card>
  );
}

// ── Macro sensitivity + business cycle (model-derived) ───────────────────────
function MacroSensitivitySection({
  factors,
  cycle,
}: {
  factors: MacroFactor[];
  cycle: { phase: string; note: string } | null;
}) {
  if (factors.length === 0 && !cycle) return null;
  return (
    <Card title="Macro Sensitivity & Business Cycle" right={<span className="text-[10px] text-slate-500">model-derived</span>}>
      {cycle && (
        <div className="border-b border-base-700/50 px-4 py-2.5">
          <span className="text-xs text-slate-400">Business Cycle Position: </span>
          <span className="text-sm font-semibold text-accent">{cycle.phase}</span>
          <div className="mt-0.5 text-[11px] text-slate-500">{cycle.note}</div>
        </div>
      )}
      <div className="grid grid-cols-1 gap-x-8 px-4 py-2 md:grid-cols-2">
        {factors.map((f) => (
          <div key={f.factor} className="flex items-center justify-between border-b border-base-700/40 py-1.5">
            <div>
              <div className="text-sm text-slate-300">{f.factor}</div>
              <div className="text-[10px] text-slate-500">{f.note}</div>
            </div>
            <Pill text={f.impact} color={IMPACT_TONE[f.impact]} />
          </div>
        ))}
      </div>
    </Card>
  );
}

// ── Catalyst tracker (Feature 9) ─────────────────────────────────────────────
function CatalystSection({
  sec,
  catalysts,
  materials,
}: {
  sec: Row;
  catalysts: CatalystsData | null;
  materials: MaterialImpact[];
}) {
  const symbol = String(sec.symbol ?? "");
  const region = String(sec.region ?? "");
  const items: { date: string | null; label: string; kind: string }[] = [];

  const nextEarn = typeof sec.next_earnings_date === "string" ? sec.next_earnings_date.slice(0, 10) : null;
  if (nextEarn) items.push({ date: nextEarn, label: "Upcoming quarterly results", kind: "Earnings" });

  // Per-company PSX announcements / corporate actions.
  for (const e of catalysts?.by_symbol?.[symbol] ?? []) {
    items.push({ date: e.date ?? null, label: e.title, kind: e.type === "corporate_action" ? "Corporate Action" : "Announcement" });
  }
  // Market-wide macro events (PSX only — PK calendar).
  if (region === "psx") {
    for (const e of (catalysts?.market_events ?? []).slice(0, 4)) {
      items.push({ date: e.date ?? null, label: e.title, kind: "Macro Event" });
    }
  }
  // Commodity-cycle catalyst from raw materials.
  const rising = materials.filter((m) => m.trend === "increasing").map((m) => m.name);
  const falling = materials.filter((m) => m.trend === "decreasing").map((m) => m.name);
  if (falling.length) items.push({ date: null, label: `Falling input costs: ${falling.join(", ")}`, kind: "Commodity Cycle" });
  if (rising.length) items.push({ date: null, label: `Rising input costs: ${rising.join(", ")}`, kind: "Commodity Cycle" });

  if (items.length === 0) return null;
  items.sort((a, b) => (a.date ?? "9999").localeCompare(b.date ?? "9999"));
  return (
    <Card title="Upcoming Catalysts">
      <div className="divide-y divide-base-700/40">
        {items.slice(0, 10).map((it, i) => (
          <div key={i} className="flex items-start justify-between gap-3 px-4 py-2">
            <div>
              <span className="rounded bg-base-700 px-1.5 py-0.5 text-[10px] uppercase tracking-wide text-slate-400">{it.kind}</span>
              <span className="ml-2 text-sm text-slate-200">{it.label}</span>
            </div>
            <span className="num shrink-0 text-[11px] text-slate-500">{it.date ?? ""}</span>
          </div>
        ))}
      </div>
    </Card>
  );
}

// ── Risk analysis ────────────────────────────────────────────────────────────
function RiskSection({ risks }: { risks: RiskItem[] }) {
  // Risk score = how many of the risk dimensions read "Low" (green) out of all.
  const green = risks.filter((r) => r.level === "Low").length;
  const scoreTone = green === risks.length ? "#22c55e" : green >= risks.length - 1 ? "#eab308" : "#f87171";
  return (
    <Card
      title="Risk Analysis"
      right={
        <span className="num text-xs font-semibold" style={{ color: scoreTone }}>
          {green}/{risks.length} Low
        </span>
      }
    >
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

// ── Valuation (cheap / fair / expensive) ─────────────────────────────────────
function classify(v: number | null, cheap: number, fair: number): { label: string; tone: string } {
  if (v == null || v <= 0) return { label: "—", tone: "#64748b" };
  if (v < cheap) return { label: "Cheap", tone: "#22c55e" };
  if (v < fair) return { label: "Fair", tone: "#eab308" };
  return { label: "Expensive", tone: "#ef4444" };
}

function ValuationSection({ detail }: { detail: CompanyDetail }) {
  const r = detail.ratios ?? {};
  const sec = detail.security as Row;
  const price = num(detail.quote?.price);
  const fwdEps = num(sec.eps_estimate_fwd);
  const fwdPe = price != null && fwdEps && fwdEps > 0 ? price / fwdEps : null;
  const rows: { label: string; value: number | null; c: [number, number] }[] = [
    { label: "P/E (TTM)", value: num(r.pe_ratio), c: [10, 20] },
    { label: "Forward P/E", value: fwdPe, c: [10, 18] },
    { label: "EV / EBITDA", value: num(r.ev_to_ebitda), c: [8, 14] },
    { label: "Price / Book", value: num(r.price_to_book), c: [1.5, 3] },
    { label: "PEG Ratio", value: num(r.peg_ratio), c: [1, 2] },
  ];
  const labels = rows.map((x) => classify(x.value, x.c[0], x.c[1]).label).filter((l) => l !== "—");
  const cheap = labels.filter((l) => l === "Cheap").length;
  const exp = labels.filter((l) => l === "Expensive").length;
  const overall = labels.length === 0 ? "—" : cheap > exp ? "Cheap" : exp > cheap ? "Expensive" : "Fair";
  const overallTone = overall === "Cheap" ? "#22c55e" : overall === "Expensive" ? "#ef4444" : "#eab308";
  const dy = num(r.dividend_yield);
  return (
    <Card title="Valuation" right={overall !== "—" ? <Pill text={overall} color={overallTone} /> : undefined}>
      <div className="grid grid-cols-1 gap-x-8 px-4 py-2 md:grid-cols-2">
        {rows.map((x) => {
          const cl = classify(x.value, x.c[0], x.c[1]);
          return (
            <div key={x.label} className="flex items-center justify-between border-b border-base-700/40 py-1.5">
              <span className="text-xs text-slate-400">{x.label}</span>
              <span className="flex items-center gap-2">
                <span className="num text-sm text-slate-200">{x.value == null ? "—" : fmtNumber(x.value)}</span>
                {cl.label !== "—" && <span className="text-[10px]" style={{ color: cl.tone }}>{cl.label}</span>}
              </span>
            </div>
          );
        })}
        <StatRow label="Dividend Yield" value={dy == null ? "—" : fmtPercent(dy)} />
      </div>
    </Card>
  );
}

// ── Company vs sector average (Feature 7) ────────────────────────────────────
const _CMP_METRICS: [string, string, "pct" | "num", boolean][] = [
  ["roe", "ROE", "pct", true], ["net_margin", "Net Margin", "pct", true],
  ["operating_margin", "Operating Margin", "pct", true],
  ["revenue_growth", "Revenue Growth", "pct", true],
  ["debt_to_equity", "Debt / Equity", "num", false],
  ["pe_ratio", "P/E", "num", false],
];

function SectorComparison({ detail, sectorStats }: { detail: CompanyDetail; sectorStats: SectorStatsData | null }) {
  const sec = detail.security as Row;
  const region = String(sec.region ?? "");
  const sector = (sec.sector as string) ?? null;
  const r = detail.ratios ?? {};
  const stat: SectorStat | undefined = (sectorStats?.[region] ?? []).find((s) => s.sector === sector);
  if (!stat || !sector) return null;
  const fmt = (v: number | null, kind: string) => (v == null ? "—" : kind === "pct" ? fmtPercent(v) : fmtNumber(v));
  return (
    <Card title="Company vs Sector" right={<span className="text-[11px] text-slate-500">{sector} · {stat.count} peers</span>}>
      <div className="px-4 py-2">
        <div className="grid grid-cols-4 gap-2 border-b border-base-700/50 pb-1 text-[10px] uppercase tracking-wide text-slate-500">
          <span>Metric</span><span className="text-right">Company</span>
          <span className="text-right">Sector Median</span><span className="text-right">vs</span>
        </div>
        {_CMP_METRICS.map(([key, label, kind, higherBetter]) => {
          const co = num(r[key]);
          const se = stat.medians[key] ?? null;
          let tone = "#94a3b8", mark = "—";
          if (co != null && se != null) {
            const better = higherBetter ? co > se : co < se;
            const same = Math.abs(co - se) < 1e-9;
            mark = same ? "≈" : better ? "▲" : "▼";
            tone = same ? "#94a3b8" : better ? "#22c55e" : "#f87171";
          }
          return (
            <div key={key} className="grid grid-cols-4 gap-2 border-b border-base-700/30 py-1.5 text-sm">
              <span className="text-slate-400">{label}</span>
              <span className="num text-right text-slate-200">{fmt(co, kind)}</span>
              <span className="num text-right text-slate-400">{fmt(se, kind)}</span>
              <span className="num text-right font-semibold" style={{ color: tone }}>{mark}</span>
            </div>
          );
        })}
      </div>
    </Card>
  );
}

// ── Raw material cost trend (Feature 4) ──────────────────────────────────────
function RawMaterialSection({ materials, outlook }: { materials: MaterialImpact[]; outlook: string | null }) {
  if (materials.length === 0 && !outlook) return null;
  return (
    <Card title="Raw Material Cost Trend & Margin Impact">
      {materials.length === 0 ? (
        <p className="p-4 text-sm text-slate-500">
          No major tracked commodity inputs map to this sector — margins are driven mainly by
          non-commodity factors.
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

// ── Mohnish Pabrai checklist ─────────────────────────────────────────────────
interface PabraiItem {
  key: string; name: string; weight: number; score: number | null;
  metric: string; benchmark: string; reason: string;
  positives: string[]; negatives: string[]; available: boolean;
}
interface PabraiBreakdown {
  overall: number; category: string; coverage: number; items: PabraiItem[];
}

function scoreTone(pct: number): string {
  return pct >= 0.7 ? "#22c55e" : pct >= 0.45 ? "#eab308" : "#f87171";
}

function PabraiSection({ scores }: { scores: Row | null }) {
  const bd = scores?.pabrai_breakdown as unknown as PabraiBreakdown | null | undefined;
  if (!bd || typeof bd !== "object" || !Array.isArray(bd.items)) return null;
  const overall = num(scores?.pabrai) ?? bd.overall ?? null;
  if (overall == null) return null;
  const stars = Math.round((overall / 100) * 5);
  const tone = scoreTone(overall / 100);

  return (
    <Card
      title="Mohnish Pabrai Checklist"
      right={
        <span className="text-xs text-slate-400">
          Coverage {Math.round((bd.coverage ?? 0) * 100)}%
        </span>
      }
    >
      <div className="flex items-center gap-4 border-b border-base-700/50 px-4 py-3">
        <div className="flex flex-col items-center">
          <span className="num text-3xl font-black" style={{ color: tone }}>{Math.round(overall)}</span>
          <span className="text-[10px] uppercase tracking-wide text-slate-500">/ 100</span>
        </div>
        <div>
          <div className="text-sm font-semibold text-slate-200">{bd.category}</div>
          <div className="text-sm" style={{ color: tone }}>
            {"★".repeat(stars)}<span className="text-slate-600">{"★".repeat(5 - stars)}</span>
          </div>
          <div className="mt-0.5 text-[11px] text-slate-500">
            Business-quality + value alignment · benchmarked by market, sector & own history
          </div>
        </div>
      </div>
      <PabraiRadar
        items={bd.items.map((it) => ({ name: it.name, score: it.score, available: it.available }))}
      />
      <div className="divide-y divide-base-700/40">
        {bd.items.map((it) => {
          const pctScore = it.score ?? 0;
          const pts = it.available && it.score != null ? it.score * it.weight : null;
          const t = scoreTone(pctScore);
          return (
            <details key={it.key} className="px-4 py-2">
              <summary className="flex cursor-pointer items-center justify-between gap-2 list-none">
                <span className="flex items-center gap-2">
                  <span style={{ color: it.available && pctScore >= 0.6 ? "#22c55e" : it.available ? "#eab308" : "#64748b" }}>
                    {!it.available ? "○" : pctScore >= 0.6 ? "✓" : "✗"}
                  </span>
                  <span className="text-sm text-slate-200">{it.name}</span>
                </span>
                <span className="flex items-center gap-2">
                  <span className="h-1.5 w-24 overflow-hidden rounded bg-base-700">
                    <span className="block h-full" style={{ width: `${Math.round(pctScore * 100)}%`, background: t }} />
                  </span>
                  <span className="num w-12 text-right text-xs" style={{ color: t }}>
                    {pts == null ? "—" : `${pts.toFixed(1)}/${it.weight}`}
                  </span>
                </span>
              </summary>
              <div className="mt-2 space-y-1 pl-6 text-[11px] text-slate-400">
                <div>
                  <span className="text-slate-300">{it.metric}</span>
                  {it.benchmark ? <span className="text-slate-500"> · vs {it.benchmark}</span> : null}
                </div>
                <div>{it.reason}</div>
                {it.positives.map((p, i) => <div key={`p${i}`} style={{ color: "#22c55e" }}>+ {p}</div>)}
                {it.negatives.map((nn, i) => <div key={`n${i}`} style={{ color: "#f87171" }}>− {nn}</div>)}
              </div>
            </details>
          );
        })}
      </div>
    </Card>
  );
}

// ── Analyst estimates & next earnings ────────────────────────────────────────
function EstimatesSection({ sec }: { sec: Row }) {
  const nextDate = typeof sec.next_earnings_date === "string" ? sec.next_earnings_date.slice(0, 10) : null;
  const epsAvg = num(sec.eps_estimate_avg);
  const epsNum = num(sec.eps_estimate_num);
  const epsGrowth = num(sec.eps_estimate_growth);
  const revAvg = num(sec.revenue_estimate_avg);
  const up = num(sec.eps_revisions_up_30d);
  const down = num(sec.eps_revisions_down_30d);

  if (!nextDate && epsAvg == null && revAvg == null && up == null) return null;

  const revisionTone = up != null && down != null && up !== down ? (up > down ? "#22c55e" : "#ef4444") : "#94a3b8";
  return (
    <Card title="Analyst Estimates & Next Earnings">
      <div className="px-4 py-2">
        {nextDate && <StatRow label="Next Earnings Date" value={nextDate} />}
        {epsAvg != null && (
          <StatRow
            label={`Consensus EPS${epsNum != null ? ` (${epsNum} analysts)` : ""}`}
            value={fmtNumber(epsAvg)}
          />
        )}
        {epsGrowth != null && (
          <StatRow
            label="Est. EPS Growth"
            value={fmtPercent(epsGrowth)}
            tone={epsGrowth >= 0 ? "#22c55e" : "#ef4444"}
          />
        )}
        {revAvg != null && <StatRow label="Consensus Revenue" value={fmtCompact(revAvg)} />}
        {(up != null || down != null) && (
          <StatRow
            label="EPS Revisions (30d)"
            value={`▲ ${up ?? 0}  ▼ ${down ?? 0}`}
            tone={revisionTone}
          />
        )}
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

// ── Data provenance (Phase 4) ────────────────────────────────────────────────
function DataSourcesCard({
  region,
  assetClass,
  meta,
}: {
  region: string;
  assetClass: string;
  meta: SnapshotMeta | null;
}) {
  const sources = dataSources(region, assetClass);
  if (sources.length === 0) return null;
  return (
    <Card
      title="Data & Sources"
      right={
        meta?.generated_at ? (
          <span className="text-[10px] text-slate-500" title={fmtSnapshotDate(meta.generated_at)}>
            {fmtSnapshotAge(meta.generated_at)}
          </span>
        ) : undefined
      }
    >
      <div className="divide-y divide-base-700/40">
        {sources.map((s) => (
          <div key={s.domain} className="px-4 py-2">
            <div className="flex items-center justify-between gap-2">
              <span className="text-sm text-slate-300">{s.domain}</span>
              <span
                className="rounded px-1.5 py-0.5 text-[10px] font-semibold"
                style={{ background: `${confidenceTone(s.confidence)}22`, color: confidenceTone(s.confidence) }}
              >
                {s.confidence}
              </span>
            </div>
            <div className="mt-0.5 text-[11px] text-slate-500">
              {s.source}
              {s.note ? <span className="text-slate-600"> · {s.note}</span> : null}
            </div>
          </div>
        ))}
      </div>
      <div className="border-t border-base-700/50 px-4 py-2 text-[10px] leading-relaxed text-slate-600">
        Research &amp; ranking intelligence only — not investment advice. No buy/sell signals or price
        targets. Heuristic reads are labelled “model-derived”.
      </div>
    </Card>
  );
}

function Centered({ children }: { children: ReactNode }) {
  return (
    <div className="flex h-full items-center justify-center bg-base-900 text-slate-400">{children}</div>
  );
}
