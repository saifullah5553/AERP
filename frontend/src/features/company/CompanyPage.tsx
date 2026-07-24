import { type ReactNode, useEffect, useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";

import { api } from "@/lib/api";
import { fmtChangePct, fmtCompact, fmtNumber, fmtPercent, titleize } from "@/lib/format";
import type { CompanyDetail, Row } from "@/types/company";
import PeersTable from "./PeersTable";
import ScoreCards from "./ScoreCards";
import ScoreHistoryChart from "./ScoreHistoryChart";
import StatementsTable, {
  BALANCE_FIELDS,
  CASHFLOW_FIELDS,
  INCOME_FIELDS,
} from "./StatementsTable";
import TradingViewChart from "./TradingViewChart";

const SIGNAL_COLOR: Record<string, string> = {
  strong_buy: "#22c55e",
  buy: "#4ade80",
  hold: "#94a3b8",
  sell: "#f87171",
  strong_sell: "#ef4444",
};

type Tab = "income" | "balance" | "cashflow" | "technicals" | "patterns" | "valuation";
const TABS: { id: Tab; label: string }[] = [
  { id: "valuation", label: "Valuation" },
  { id: "income", label: "Income" },
  { id: "balance", label: "Balance" },
  { id: "cashflow", label: "Cash Flow" },
  { id: "technicals", label: "Technicals" },
  { id: "patterns", label: "Patterns" },
];

type Fmt = "num" | "pct" | "compact";
function metricValue(row: Row | null, key: string, fmt: Fmt): string {
  const v = row?.[key];
  if (typeof v !== "number") return "—";
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
  ["roe", "ROE", "pct"], ["roa", "ROA", "pct"], ["roic", "ROIC", "pct"],
  ["gross_margin", "Gross Margin", "pct"], ["operating_margin", "Op Margin", "pct"],
  ["net_margin", "Net Margin", "pct"], ["debt_to_equity", "Debt/Equity", "num"],
  ["current_ratio", "Current Ratio", "num"], ["quick_ratio", "Quick Ratio", "num"],
  ["interest_coverage", "Interest Cov", "num"], ["altman_z", "Altman Z", "num"],
  ["piotroski_f", "Piotroski F", "num"], ["revenue_growth", "Rev Growth", "pct"],
  ["eps_growth", "EPS Growth", "pct"], ["dividend_yield", "Div Yield", "pct"],
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

export default function CompanyPage() {
  const { symbol = "" } = useParams();
  const [data, setData] = useState<CompanyDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [tab, setTab] = useState<Tab>("valuation");

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

  const changePct = useMemo(() => {
    const v = data?.quote?.change_pct;
    return typeof v === "number" ? v : null;
  }, [data]);

  if (error) {
    return <Centered>Could not load {symbol}: {error}</Centered>;
  }
  if (!data) {
    return <Centered>Loading {symbol}…</Centered>;
  }

  const sec = data.security;
  const signalType = typeof data.signal?.signal_type === "string" ? data.signal.signal_type : null;
  const price = typeof data.quote?.price === "number" ? data.quote.price : null;

  return (
    <div className="h-full overflow-y-auto bg-base-900 text-slate-200">
      {/* Header */}
      <header className="sticky top-0 z-10 flex items-center justify-between border-b border-base-600 bg-base-900/95 px-5 py-3 backdrop-blur">
        <div className="flex items-center gap-4">
          <Link to="/" className="text-sm text-slate-400 hover:text-accent">
            ← Screener
          </Link>
          <div>
            <div className="flex items-center gap-2">
              <span className="text-xl font-bold text-accent">{sec.symbol}</span>
              <span className="rounded bg-base-700 px-1.5 py-0.5 text-[10px] text-slate-400">
                {sec.market_code}
              </span>
            </div>
            <div className="text-sm text-slate-400">{sec.name}</div>
          </div>
        </div>
        <div className="flex items-center gap-4">
          <div className="text-right">
            <div className="num text-lg font-semibold">{fmtNumber(price)}</div>
            <div
              className="num text-sm"
              style={{ color: changePct && changePct > 0 ? "#22c55e" : changePct && changePct < 0 ? "#ef4444" : "#94a3b8" }}
            >
              {fmtChangePct(changePct)}
            </div>
          </div>
          {signalType && (
            <span
              className="rounded px-3 py-1 text-sm font-semibold"
              style={{ background: "#1e293b", color: SIGNAL_COLOR[signalType] ?? "#94a3b8" }}
            >
              {String(data.signal?.label ?? titleize(signalType))}
            </span>
          )}
        </div>
      </header>

      {/* Body */}
      <div className="grid gap-4 p-4 lg:grid-cols-3">
        <div className="space-y-4 lg:col-span-2">
          <TradingViewChart symbol={data.tradingview_symbol} />

          <div className="rounded border border-base-600 bg-base-800">
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
          </div>
        </div>

        <div className="space-y-4">
          <ScoreCards scores={data.scores} />
          <div className="rounded border border-base-600 bg-base-800 p-4">
            <div className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-400">
              AI Summary
            </div>
            <p className="text-sm leading-relaxed text-slate-300">{data.ai_summary}</p>
          </div>
          <ScoreHistoryChart history={data.score_history} />
          <PeersTable peers={data.peers} />
        </div>
      </div>
    </div>
  );
}

function PatternsList({ patterns }: { patterns: Row[] }) {
  if (patterns.length === 0) {
    return <div className="p-4 text-sm text-slate-500">No active patterns detected.</div>;
  }
  return (
    <div className="space-y-2 p-4">
      {patterns.map((p, i) => {
        const dir = String(p.direction ?? "");
        const color = dir === "bullish" ? "#22c55e" : dir === "bearish" ? "#ef4444" : "#94a3b8";
        const conf = typeof p.confidence === "number" ? p.confidence : 0;
        return (
          <div key={i} className="flex items-center justify-between rounded border border-base-700 bg-base-900 px-3 py-2">
            <div>
              <span className="font-medium text-slate-200">{titleize(String(p.name))}</span>
              <span className="ml-2 text-xs uppercase" style={{ color }}>{dir}</span>
              <span className="ml-2 text-[10px] text-slate-500">{String(p.category)}</span>
            </div>
            <div className="flex items-center gap-4 text-xs text-slate-400">
              {typeof p.target_price === "number" && <span>Target {fmtNumber(p.target_price)}</span>}
              <span className="num">conf {(conf * 100).toFixed(0)}%</span>
            </div>
          </div>
        );
      })}
    </div>
  );
}

function Centered({ children }: { children: ReactNode }) {
  return (
    <div className="flex h-full items-center justify-center bg-base-900 text-slate-400">
      {children}
    </div>
  );
}
