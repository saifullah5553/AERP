// Pure, deterministic equity-research helpers.
//
// Everything here is derived from data already computed by the backend (composite
// scores, financial ratios, technical indicators, patterns). No predictions, no
// buy/sell calls — just labelling and framing of real numbers for presentation.

import type { CompanyDetail, Row } from "@/types/company";

export type Level = "Low" | "Medium" | "High" | "Unknown";
export type Condition = "Bullish" | "Bearish" | "Neutral";

/** Safe numeric read from a dynamic column bag. */
export function num(v: unknown): number | null {
  if (typeof v === "number") return Number.isFinite(v) ? v : null;
  if (typeof v === "string" && v.trim() !== "" && !Number.isNaN(Number(v))) return Number(v);
  return null;
}

// ── Header labels ───────────────────────────────────────────────────────────
export function investmentGrade(composite: number | null): string {
  if (composite == null) return "—";
  if (composite >= 80) return "A+";
  if (composite >= 70) return "A";
  if (composite >= 60) return "B+";
  if (composite >= 50) return "B";
  return "C";
}

export function marketCondition(composite: number | null): Condition {
  if (composite == null) return "Neutral";
  if (composite >= 55) return "Bullish";
  if (composite <= 45) return "Bearish";
  return "Neutral";
}

export function strengthLabel(score: number | null): "Strong" | "Average" | "Weak" {
  if (score == null) return "Weak";
  if (score >= 65) return "Strong";
  if (score >= 45) return "Average";
  return "Weak";
}

export interface ScoreSet {
  overall: number | null;
  fundamental: number | null;
  technical: number | null;
  quality: number | null;
  risk: number | null;
  momentum: number | null;
}

export function scoreSet(detail: CompanyDetail): ScoreSet {
  const s = detail.scores ?? {};
  return {
    overall: num(s.composite),
    fundamental: num(s.fundamental),
    technical: num(s.technical),
    quality: num(s.quality),
    risk: num(s.risk),
    momentum: num(s.momentum),
  };
}

// ── Technical intelligence (chart-free) ──────────────────────────────────────
export interface TechnicalRead {
  trend: "Bullish" | "Bearish" | "Sideways";
  momentum: "Strong" | "Weak";
  aboveSma50: boolean | null;
  aboveSma200: boolean | null;
  rsi: number | null;
  rsiCondition: "Overbought" | "Oversold" | "Neutral";
  volume: "Increasing" | "Decreasing" | "Normal";
  pattern: string | null;
}

export function technicalRead(detail: CompanyDetail): TechnicalRead {
  const t = detail.technical ?? {};
  const q = detail.quote ?? {};
  const close = num(q.price) ?? num(t.sma_20);
  const sma50 = num(t.sma_50);
  const sma200 = num(t.sma_200);
  const rsi = num(t.rsi_14);
  const mfi = num(t.mfi_14);
  const macdHist = num(t.macd_hist);
  const mom = num(t.momentum);

  let trend: TechnicalRead["trend"] = "Sideways";
  if (close != null && sma50 != null && sma200 != null) {
    if (close > sma50 && sma50 > sma200) trend = "Bullish";
    else if (close < sma50 && sma50 < sma200) trend = "Bearish";
  } else if (close != null && sma50 != null) {
    trend = close > sma50 ? "Bullish" : "Bearish";
  }

  const momentumStrong = (macdHist ?? mom ?? 0) > 0 && (rsi ?? 50) >= 50;

  let rsiCondition: TechnicalRead["rsiCondition"] = "Neutral";
  if (rsi != null) rsiCondition = rsi >= 70 ? "Overbought" : rsi <= 30 ? "Oversold" : "Neutral";

  let volume: TechnicalRead["volume"] = "Normal";
  if (mfi != null) volume = mfi >= 60 ? "Increasing" : mfi <= 40 ? "Decreasing" : "Normal";

  // Prefer the top chart pattern, else the top candlestick.
  const chart = detail.patterns.find((p) => String(p.category) === "chart");
  const candle = detail.patterns.find((p) => String(p.category) === "candlestick");
  const pattern = (chart ?? candle)?.name != null ? String((chart ?? candle)?.name) : null;

  return {
    trend,
    momentum: momentumStrong ? "Strong" : "Weak",
    aboveSma50: close != null && sma50 != null ? close > sma50 : null,
    aboveSma200: close != null && sma200 != null ? close > sma200 : null,
    rsi,
    rsiCondition,
    volume,
    pattern,
  };
}

/** Map a chart/candlestick pattern to a plain accumulation/distribution read. */
export function patternRead(detail: CompanyDetail): string | null {
  const names = detail.patterns.map((p) => String(p.name).toLowerCase());
  const dirs = detail.patterns.map((p) => String(p.direction).toLowerCase());
  if (names.some((n) => n.includes("bottom") || n.includes("bull_flag") || n.includes("ascending")))
    return "Accumulation";
  if (names.some((n) => n.includes("top") || n.includes("bear_flag") || n.includes("descending")))
    return "Distribution";
  if (names.some((n) => n.includes("triangle") || n.includes("rectangle") || n.includes("consolid")))
    return "Consolidation";
  if (dirs.includes("bullish")) return "Breakout Setup";
  return null;
}

// ── Fundamentals ─────────────────────────────────────────────────────────────
export function latestCashFlow(detail: CompanyDetail): { fcf: number | null; trend: string } {
  // Statements arrive newest-first (fiscal_date DESC), so the latest period is [0].
  const cf = detail.statements?.cashflow ?? [];
  const latest = cf[0] as Row | undefined;
  const prev = cf[1] as Row | undefined;
  const fcf = latest ? num(latest.free_cash_flow) ?? num(latest.operating_cash_flow) : null;
  const cur = latest ? num(latest.operating_cash_flow) : null;
  const old = prev ? num(prev.operating_cash_flow) : null;
  let trend = "—";
  if (cur != null && old != null) trend = cur > old * 1.02 ? "Improving" : cur < old * 0.98 ? "Declining" : "Stable";
  else if (fcf != null) trend = fcf > 0 ? "Positive" : "Negative";
  return { fcf, trend };
}

// Banks/insurers/brokerages: leverage, current ratio and free cash flow are not
// comparable to industrials, so we treat those metrics sector-appropriately.
const FINANCIAL_RE = /bank|insur|financ|modaraba|securities|brokerage|asset manage|\binvest/i;
export function isFinancial(sector: string | null, industry: string | null): boolean {
  return FINANCIAL_RE.test(`${sector ?? ""} ${industry ?? ""}`);
}

// ── Risk analysis ────────────────────────────────────────────────────────────
export interface RiskItem {
  name: string;
  level: Level;
  note: string;
}

const CURRENCY_RISK: Record<string, Level> = { PKR: "High", INR: "Medium", TRY: "High", BRL: "Medium" };

export function riskAnalysis(
  detail: CompanyDetail,
  ctx: { regionCondition?: Condition; commodity?: CommoditySummary },
): RiskItem[] {
  const r = detail.ratios ?? {};
  const sec = detail.security as Row;
  const fin = isFinancial((sec.sector as string) ?? null, (sec.industry as string) ?? null);
  const de = num(r.debt_to_equity);
  const pe = num(r.pe_ratio);
  const cr = num(r.current_ratio);
  const currency = String(sec.currency ?? "USD");

  const band = (v: number | null, hi: number, mid: number, invert = false): Level => {
    if (v == null) return "Unknown";
    const high = invert ? v < mid : v > hi;
    const medium = invert ? v < hi : v > mid;
    return high ? "High" : medium ? "Medium" : "Low";
  };

  const commodityLevel: Level = !ctx.commodity?.hasInputs
    ? "Low"
    : ctx.commodity.anyIncreasing
      ? "High"
      : ctx.commodity.favorable
        ? "Low"
        : "Medium";

  const sectorLevel: Level =
    ctx.regionCondition === "Bearish" ? "High" : ctx.regionCondition === "Bullish" ? "Low" : "Medium";

  const items: RiskItem[] = [];
  // Leverage & liquidity are only comparable for non-financials.
  if (fin) {
    items.push({ name: "Leverage Risk", level: "Unknown", note: "Not comparable for financials" });
  } else {
    items.push({ name: "Debt Risk", level: band(de, 1.5, 0.75), note: de != null ? `D/E ${de.toFixed(2)}` : "No data" });
    items.push({ name: "Liquidity Risk", level: band(cr, 1.5, 1.0, true), note: cr != null ? `Current ratio ${cr.toFixed(2)}` : "No data" });
  }
  items.push({ name: "Valuation Risk", level: band(pe, 35, 20), note: pe != null ? `P/E ${pe.toFixed(1)}` : "No data" });
  items.push({ name: "Commodity Risk", level: commodityLevel, note: ctx.commodity?.hasInputs ? "Input-cost exposure" : "Low input-cost exposure" });
  items.push({ name: "Sector Risk", level: sectorLevel, note: "From market condition" });
  items.push({ name: "Currency Risk", level: CURRENCY_RISK[currency] ?? "Low", note: `Reporting currency ${currency}` });
  return items;
}

// ── Investment checklist ─────────────────────────────────────────────────────
export interface CheckItem {
  label: string;
  pass: boolean;
}

export interface CommoditySummary {
  hasInputs: boolean;
  anyIncreasing: boolean;
  favorable: boolean; // majority of inputs decreasing
}

export function investmentChecklist(
  detail: CompanyDetail,
  ctx: { tech: TechnicalRead; regionCondition?: Condition; commodity?: CommoditySummary; fcf: number | null },
): CheckItem[] {
  const r = detail.ratios ?? {};
  const sec = detail.security as Row;
  const fin = isFinancial((sec.sector as string) ?? null, (sec.industry as string) ?? null);
  const revenue = num(r.revenue_growth);
  const eps = num(r.eps_growth);
  const roe = num(r.roe);
  const de = num(r.debt_to_equity);
  const netMargin = num(r.net_margin);
  return [
    { label: "Revenue Growth", pass: revenue != null && revenue > 0 },
    { label: "Earnings Growth", pass: eps != null && eps > 0 },
    { label: "Strong ROE (>15%)", pass: roe != null && roe >= 0.15 },
    // Banks are structurally leveraged; use a bank-appropriate bar instead of <0.6.
    fin
      ? { label: "Prudent Leverage (bank)", pass: de != null && de < 3 }
      : { label: "Low Debt (D/E <0.6)", pass: de != null && de < 0.6 },
    // FCF is not meaningful for financials → use profitability as the cash proxy.
    fin
      ? { label: "Profitable", pass: netMargin != null && netMargin > 0 }
      : { label: "Positive Cash Flow", pass: ctx.fcf != null && ctx.fcf > 0 },
    { label: "Technical Trend", pass: ctx.tech.trend === "Bullish" },
    { label: "Sector Strength", pass: ctx.regionCondition === "Bullish" },
    { label: "Raw Material Environment", pass: !!ctx.commodity && (!ctx.commodity.hasInputs || ctx.commodity.favorable) },
  ];
}
