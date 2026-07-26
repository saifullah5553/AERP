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
}
export interface CatalystsData {
  market_events: CatalystEvent[];
  by_symbol: Record<string, CatalystEvent[]>;
}

export interface SwingRow {
  provider_symbol: string;
  symbol: string;
  name: string | null;
  market_code: string | null;
  region: MarketRegion;
  sector: string | null;
  swing_score: number;
  fundamental: number | null;
  catalyst: number | null;
  technical: number | null;
  risk: number | null;
  composite: number | null;
  price: number | null;
  change_pct: number | null;
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
  swing_score?: number | null;
  signal: SignalType | null;
  signal_label: string | null;
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
  sort_by?: string;
  sort_dir?: "asc" | "desc";
}
