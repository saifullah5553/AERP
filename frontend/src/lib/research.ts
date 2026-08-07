// Pure, deterministic equity-research helpers.
//
// Everything here is derived from data already computed by the backend (composite
// scores, financial ratios, technical indicators, patterns). No predictions, no
// buy/sell calls — just labelling and framing of real numbers for presentation.

import type { CountryRegime } from "@/types/api";
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
  // "Fundamental" must be the Fundamental Quality Score - the same number the scorecard below
  // it reports and the same one the screener ranks on. `scores.fundamental` is a different,
  // older ratio-based metric that survives only as an input to the composite and the
  // backtests; showing it under this label put 77 in the header against 93.7 in the card on
  // the same page, both called fundamental, and neither equal to the 85.4 the grid was sorting
  // by. Three numbers, one question.
  const card = detail.fundamental_scorecard?.score;
  return {
    overall: num(s.composite),
    fundamental: card != null ? num(card) : num(s.fundamental),
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

// ── Macro sensitivity (model-derived) ────────────────────────────────────────
// Combines a sector's structural exposure with the LIVE regime direction so it
// updates as macro changes. A rule-based interpretation, not hard data.
export interface MacroFactor {
  factor: string;
  impact: "Positive" | "Neutral" | "Negative";
  note: string;
}

const _RATE_POS = /bank|insur|financ|securit|modaraba/i;   // gain from higher rates
const _RATE_NEG = /cement|steel|engineer|auto|textile|utilit|power|chemical|leasing|real estate|glass/i;
const _EXPORTER = /textile|apparel|technolog|software|it services|pharma|leather|surgical|rice|sports|weaving|spinning/i;
const _IMPORTER = /automobile|oil & gas marketing|refiner|chemical|electronic|appliance|steel/i;
const _ENERGY_PROD = /exploration|e&p|oil & gas dev|petroleum|oil & gas exploration/i;
const _ENERGY_CONS = /cement|steel|auto|airline|transport|chemical|power|glass|fertiliz/i;

function _rising(regime: CountryRegime | undefined, key: string): boolean | null {
  const s = regime?.signals.find((x) => x.key === key)?.score;
  if (s == null) return null;
  // rate/inflation/commodity signals score high when FALLING (supportive).
  return s <= 40 ? true : s >= 60 ? false : null; // true = factor is rising
}

export function macroSensitivity(
  sector: string | null,
  industry: string | null,
  regime: CountryRegime | undefined,
): MacroFactor[] {
  if (!regime) return [];
  const hay = `${sector ?? ""} ${industry ?? ""}`;
  const out: MacroFactor[] = [];
  const impactFrom = (exposure: number, rising: boolean | null): MacroFactor["impact"] => {
    if (exposure === 0 || rising == null) return "Neutral";
    const good = (exposure > 0 && rising) || (exposure < 0 && !rising);
    return good ? "Positive" : "Negative";
  };

  // Interest rates
  const rateExp = _RATE_POS.test(hay) ? 1 : _RATE_NEG.test(hay) ? -1 : 0;
  const ratesRising = _rising(regime, "rate_cycle");
  out.push({
    factor: "Interest Rates",
    impact: impactFrom(rateExp, ratesRising),
    note: rateExp > 0 ? "Higher-rate beneficiary (net interest margins)"
      : rateExp < 0 ? "Leverage-sensitive to higher rates"
      : "Limited direct rate sensitivity",
  });
  // Currency (local depreciation)
  const ccyExp = _EXPORTER.test(hay) ? 1 : _IMPORTER.test(hay) ? -1 : 0; // +1 gains from weak local ccy
  const ccyWeak = _rising(regime, "currency_trend"); // score low = weak → rising()=true means weak
  out.push({
    factor: "Currency",
    impact: impactFrom(ccyExp, ccyWeak),
    note: ccyExp > 0 ? "Exporter — gains when local currency weakens"
      : ccyExp < 0 ? "Import-reliant — hurt by currency weakness"
      : "Limited FX sensitivity",
  });
  // Energy / commodity input costs
  const oilExp = _ENERGY_PROD.test(hay) ? 1 : _ENERGY_CONS.test(hay) ? -1 : 0;
  const costsRising = _rising(regime, "commodity_env");
  out.push({
    factor: "Oil / Commodity Costs",
    impact: impactFrom(oilExp, costsRising),
    note: oilExp > 0 ? "Energy/commodity producer — gains when prices rise"
      : oilExp < 0 ? "Input-cost sensitive — hurt by rising commodity prices"
      : "Limited commodity sensitivity",
  });
  // Inflation
  const inflRising = _rising(regime, "inflation_trend");
  const inflExp = _RATE_POS.test(hay) ? 0 : -1; // most non-financials hurt by rising inflation
  out.push({
    factor: "Inflation",
    impact: impactFrom(inflExp, inflRising),
    note: inflExp < 0 ? "Margins pressured by rising inflation" : "Limited direct inflation sensitivity",
  });
  return out;
}

// ── Business cycle position (model-derived) ──────────────────────────────────
export function businessCycle(detail: CompanyDetail): { phase: string; note: string } | null {
  const inc = detail.statements?.income ?? []; // newest-first
  if (inc.length < 3) return null;
  const rev = (i: number) => num(inc[i]?.revenue);
  const ni = (i: number) => num(inc[i]?.net_income);
  const r0 = rev(0), r1 = rev(1), r2 = rev(2);
  if (r0 == null || r1 == null || r2 == null || r1 === 0 || r2 === 0) return null;
  const gRecent = (r0 - r1) / Math.abs(r1);
  const gPrev = (r1 - r2) / Math.abs(r2);
  const m0 = ni(0) != null && r0 ? (ni(0) as number) / r0 : null;
  const m1 = ni(1) != null && r1 ? (ni(1) as number) / r1 : null;
  const marginUp = m0 != null && m1 != null ? m0 > m1 : null;

  let phase: string, note: string;
  if (gRecent < 0 && marginUp) {
    phase = "Turnaround"; note = "Revenue still soft but margins are recovering.";
  } else if (gRecent < -0.02) {
    phase = "Slowdown"; note = "Revenue contracting versus the prior year.";
  } else if (gPrev <= 0.02 && gRecent > 0.05) {
    phase = "Recovery"; note = "Growth re-accelerating from a low base.";
  } else if (gRecent > 0.05 && gRecent >= gPrev) {
    phase = "Expansion"; note = "Accelerating growth with healthy momentum.";
  } else if (gRecent > 0 && gRecent < gPrev) {
    phase = "Peak / Maturing"; note = "Still growing but the pace is decelerating.";
  } else {
    phase = "Stable"; note = "Steady growth with no strong cyclical signal.";
  }
  return { phase, note };
}

// ── Wyckoff phase (model-derived) ────────────────────────────────────────────
export function wyckoffPhase(detail: CompanyDetail): { phase: string; note: string } | null {
  const t = detail.technical ?? {};
  const q = detail.quote ?? {};
  const close = num(q.price) ?? num(t.sma_20);
  const s50 = num(t.sma_50);
  const s200 = num(t.sma_200);
  const fromHigh = num(t.pct_from_52w_high); // fraction, <= 0
  if (close == null || s50 == null) return null;

  if (s200 != null && close > s50 && s50 > s200) {
    return { phase: "Markup", note: "Sustained uptrend above rising moving averages." };
  }
  if (s200 != null && close < s50 && s50 < s200) {
    return { phase: "Markdown", note: "Sustained downtrend below falling moving averages." };
  }
  if (fromHigh != null && fromHigh <= -0.25 && close >= s50 * 0.95) {
    return { phase: "Accumulation", note: "Basing well below the 52-week high — potential accumulation." };
  }
  if (fromHigh != null && fromHigh >= -0.05 && close < s50) {
    return { phase: "Distribution", note: "Rolling over near the highs — potential distribution." };
  }
  return { phase: "Consolidation", note: "Range-bound; no decisive Wyckoff phase yet." };
}
