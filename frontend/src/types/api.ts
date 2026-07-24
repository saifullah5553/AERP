// Mirrors the backend Pydantic schemas (app/schemas/screener.py, common.py).

export type AssetClass =
  | "equity"
  | "crypto"
  | "forex"
  | "commodity"
  | "index"
  | "etf";

export type MarketRegion = "psx" | "us" | "india" | "gcc" | "global";

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
  signal: SignalType | null;
  signal_label: string | null;
  top_pattern: string | null;
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
