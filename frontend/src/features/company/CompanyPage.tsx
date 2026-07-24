import { type ReactNode, useEffect, useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";

import { api } from "@/lib/api";
import { fmtChangePct, fmtCompact, fmtNumber, fmtPercent, titleize } from "@/lib/format";
import { openQuoteStream } from "@/lib/liveQuotes";
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

  // Live price updates for this security's header.
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
          <InsiderCard summary={data.insider_summary} transactions={data.insider} />
          <ScoreHistoryChart history={data.score_history} />
          <PeersTable peers={data.peers} />
          <NewsCard news={data.news} />
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

const INSIDER_COLOR: Record<string, string> = {
  strong_buying: "#22c55e",
  buying: "#4ade80",
  neutral: "#94a3b8",
  selling: "#f87171",
  strong_selling: "#ef4444",
  no_activity: "#64748b",
};

function InsiderCard({ summary, transactions }: { summary: Row | null; transactions: Row[] }) {
  const activity = typeof summary?.activity === "string" ? summary.activity : "no_activity";
  const score = typeof summary?.score === "number" ? summary.score : null;
  const buy = typeof summary?.buy_count === "number" ? summary.buy_count : 0;
  const sell = typeof summary?.sell_count === "number" ? summary.sell_count : 0;
  const window = typeof summary?.window_days === "number" ? summary.window_days : 60;
  const color = INSIDER_COLOR[activity] ?? "#94a3b8";
  const recent = (transactions ?? []).slice(0, 6);

  if (activity === "no_activity" && recent.length === 0) {
    return null;
  }

  return (
    <div className="rounded border border-base-600 bg-base-800 p-4">
      <div className="mb-2 flex items-center justify-between">
        <span className="text-xs font-semibold uppercase tracking-wide text-slate-400">
          Insider Activity ({window}d)
        </span>
        {score !== null && (
          <span className="num text-sm font-semibold" style={{ color }}>
            {score.toFixed(0)}/100
          </span>
        )}
      </div>
      <div className="text-sm font-medium" style={{ color }}>
        {titleize(activity)}
      </div>
      {(buy > 0 || sell > 0) && (
        <div className="mt-1 text-xs text-slate-400">
          {buy} insider{buy === 1 ? "" : "s"} buying · {sell} selling
        </div>
      )}
      {recent.length > 0 && (
        <div className="mt-3 space-y-1 border-t border-base-700/50 pt-2">
          {recent.map((t, i) => {
            const type = String(t.transaction_type ?? "");
            const isBuy = type.toLowerCase() === "buy";
            return (
              <div key={i} className="flex items-center justify-between text-xs">
                <span className="truncate text-slate-400" title={String(t.insider_name ?? "")}>
                  {String(t.insider_name ?? "—").slice(0, 22)}
                </span>
                <span className="num" style={{ color: isBuy ? "#22c55e" : "#ef4444" }}>
                  {isBuy ? "BUY" : "SELL"} {fmtCompact(typeof t.shares === "number" ? t.shares : null)}
                </span>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

function NewsCard({ news }: { news: Row[] }) {
  if (!news || news.length === 0) {
    return null;
  }
  return (
    <div className="rounded border border-base-600 bg-base-800">
      <div className="border-b border-base-600 px-4 py-2 text-xs font-semibold uppercase tracking-wide text-slate-400">
        Latest News
      </div>
      <div className="divide-y divide-base-700/40">
        {news.slice(0, 6).map((n, i) => {
          const title = typeof n.title === "string" ? n.title : "";
          const url = typeof n.url === "string" ? n.url : undefined;
          const source = typeof n.source === "string" ? n.source : "";
          const when = typeof n.published_at === "string" ? n.published_at.slice(0, 10) : "";
          return (
            <a
              key={i}
              href={url}
              target="_blank"
              rel="noreferrer"
              className="block px-4 py-2 hover:bg-base-700/40"
            >
              <div className="text-sm text-slate-200">{title}</div>
              <div className="mt-0.5 text-[11px] text-slate-500">
                {source}
                {source && when ? " · " : ""}
                {when}
              </div>
            </a>
          );
        })}
      </div>
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
