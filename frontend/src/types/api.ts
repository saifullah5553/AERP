// Mirrors the backend Pydantic schemas (app/schemas/screener.py, common.py).

export type AssetClass =
  | "equity"
  | "crypto"
  | "forex"
  | "commodity"
  | "index"
  | "etf";

export type MarketRegion = "psx" | "us" | "india" | "gcc" | "australia" | "global";

export interface RegimeSignal {
  key: string;
  label: string;
  value: string;
  score: number | null;
  note: string;
  /** Period the reading describes ("Jun 26"). Absent for signals with no dated series. */
  as_of?: string;
}
export interface CountryRegime {
  region: MarketRegion;
  label: string;
  regime: "Bullish" | "Neutral" | "Bearish";
  health: number | null;
  explanation: string;
  signals: RegimeSignal[];
}
export interface MacroRegimeData {
  countries: Record<string, CountryRegime>;
}

export interface SnapshotMeta {
  generated_at: string | null;
  securities?: number | null;
  companies?: number | null;
  mode?: string | null;
}

export interface CatalystEvent {
  date: string | null;
  title: string;
  category?: string | null;
  note?: string | null;
  type?: string;
  pdf_url?: string | null;
}
export interface CatalystsData {
  market_events: CatalystEvent[];
  by_symbol: Record<string, CatalystEvent[]>;
}

export interface SectorStat {
  sector: string;
  region: MarketRegion;
  count: number;
  score: number;
  technical: number | null;
  fundamental: number | null;
  pabrai: number | null;
  momentum: number | null;
  breadth_above_50dma: number | null;
  trend: string;
  medians: Record<string, number | null>;
}
export type SectorStatsData = Record<string, SectorStat[]>;

export interface MarketPulse {
  region: MarketRegion;
  label: string;
  pulse: "bullish" | "bearish" | "neutral";
  avg_composite: number;
  count: number;
  bullish: number;
  bearish: number;
  neutral: number;
  /** Names that ROSE / FELL today. Not the same as bullish/bearish, which is our score. */
  advancers?: number;
  decliners?: number;
}

export type SignalType =
  | "strong_buy"
  | "buy"
  | "hold"
  | "sell"
  | "strong_sell";

export interface ScreenerRow {
  security_id: number;
  symbol: string;
  provider_symbol: string;
  name: string | null;
  market_code: string;
  region: MarketRegion;
  asset_class: AssetClass;
  sector: string | null;
  industry: string | null;
  currency: string | null;

  price: number | null;
  change: number | null;
  change_pct: number | null;
  volume: number | null;
  market_cap: number | null;

  pe_ttm: number | null;
  roe: number | null;
  debt_to_equity: number | null;
  revenue_growth: number | null;
  eps_growth: number | null;
  dividend_yield: number | null;

  fundamental_score: number | null;
  technical_score: number | null;
  composite_score: number | null;
  pabrai_score: number | null;
  // Strategy engine (quality gate -> price-action entry). Backtests showed the fundamental
  // gate carries the edge, so these lead the screener.
  strategy_action?: "buy" | "hold" | "watch" | "avoid" | null;
  strategy_conviction?: number | null;
  quality_score?: number | null;
  /** 0-100: how much real data is behind quality_score. */
  quality_confidence?: number | null;
  /** Exceptional / Excellent / Good / Acceptable / Weak / Poor / Very Poor. */
  quality_grade?: string | null;
  quality_passed?: boolean | null;
  /** Six levels, fitted across the whole TTM history rather than read off its endpoints. */
  quality_trend?:
    | "strongly_improving"
    | "improving"
    | "stable"
    | "mixed"
    | "deteriorating"
    | "strongly_deteriorating"
    | "unknown"
    | null;
  /** The LATEST step: this TTM against the one before it - the most recent signal. */
  quality_change?: number | null;
  /** Fundamental score at each trailing-twelve-month point, oldest to newest (up to 20). */
  score_history?: number[] | null;
  /** Period-end date for each score, aligned with score_history. */
  score_history_dates?: string[] | null;
  /** The latest score placed against the company's OWN five-year record. 62 means one thing
   *  for a company never above 60 and another for one that spent four years in the eighties. */
  score_high?: number | null;
  score_low?: number | null;
  score_avg?: number | null;
  score_percentile?: number | null;
  /** The six category marks for the newest period, out of their own budgets:
   *  growth 20, profitability 20, cash_flow 25, balance_sheet 15, liquidity 10,
   *  working_capital 10. */
  score_cats?: Record<string, number> | null;
  results_through?: string | null;
  entry_score?: number | null;
  signal: SignalType | null;
  signal_label: string | null;
  signal_since?: string | null;
  price_at_signal?: number | null;
  signal_return_pct?: number | null;
  top_pattern: string | null;
  top_candlestick: string | null;
  top_chart_pattern: string | null;
  insider_score: number | null;
  insider_activity: string | null;
  scored_on: string | null;
}

export interface Page<T> {
  items: T[];
  total: number;
  page: number;
  page_size: number;
}

export interface ScreenerQuery {
  page: number;
  page_size: number;
  search?: string;
  region?: MarketRegion;
  asset_class?: AssetClass;
  sector?: string;
  min_composite?: number;
  sentiment?: "bullish" | "bearish" | "neutral";
  /** Price direction today. Distinct from `sentiment`, which is our composite score. */
  move?: "up" | "down";
  has_fundamentals?: boolean;
  sort_by?: string;
  sort_dir?: "asc" | "desc";
}
