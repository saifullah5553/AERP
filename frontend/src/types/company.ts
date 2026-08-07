export interface ScorePoint {
  as_of: string;
  composite: number | null;
  fundamental: number | null;
  technical: number | null;
  momentum: number | null;
  quality: number | null;
  risk: number | null;
}

export interface Peer {
  provider_symbol: string;
  symbol: string;
  name: string | null;
  sector: string | null;
  composite_score: number | null;
  price: number | null;
}

// Statement/ratio/quote rows are dynamic column bags from the backend.
export type Row = Record<string, number | string | null>;

export interface CompanyDetail {
  security: Row & { symbol: string; market_code: string | null; region: string | null };
  tradingview_symbol: string | null;
  quote: Row | null;
  scores: Row | null;
  signal: Row | null;
  fundamentals: Row | null;
  ratios: Row | null;
  technical: Row | null;
  statements: { income: Row[]; balance: Row[]; cashflow: Row[] };
  patterns: Row[];
  score_history: ScorePoint[];
  dividends: Row[];
  estimates: Row[];
  peers: Peer[];
  news: Row[];
  insider: Row[];
  insider_summary: Row | null;
  ai_summary: string;
  fundamental_scorecard?: FundamentalScorecard | null;
  /** The fundamental score for EVERY stored TTM period, oldest first, each with the six
   *  category marks that produced it. This is the primary output of the scoring engine - the
   *  latest score is simply its last point. */
  quality_history?: QualityPoint[] | null;
  /** Direction fitted across the whole history, plus where the latest score sits in it. */
  quality_trend?: QualityTrend | null;
}

export interface QualityPoint {
  date: string;
  score: number;
  passed?: boolean | null;
  period?: string;
  /** Marks out of growth 20, profitability 20, cash_flow 25, balance_sheet 15,
   *  liquidity 10, working_capital 10. */
  cats?: Record<string, number> | null;
  confidence?: number | null;
}

export interface QualityTrend {
  direction: string;
  /** The LATEST step - this TTM against the one before it. */
  change: number | null;
  points: number;
  period?: string;
  score_high?: number | null;
  score_low?: number | null;
  score_avg?: number | null;
  score_percentile?: number | null;
  score_periods?: number | null;
}

/** The six-category Fundamental Quality Score, as computed for this company. */
export interface ScoreCategory {
  earned: number;
  points: number;
  parts: Record<string, number | null>;
}
export interface FundamentalScorecard {
  score: number | null;
  /** 0-100: how much of the score rests on real data rather than what survived. */
  confidence: number | null;
  grade: string;
  categories: Record<string, ScoreCategory>;
  metrics: Record<string, number | null>;
  /** Earnings-quality red flags, e.g. profit not backed by operating cash. */
  flags: string[];
}
