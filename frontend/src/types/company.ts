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

/** The price-action read: the whole technical analysis, not just its score.
 *
 * Replaces the indicator block. There is no RSI, MACD or moving average here because the
 * engine that produced them is gone - what a chart shows is structure, levels, volume and
 * what the last bars did, so that is what the page shows.
 */
export interface PriceActionZone {
  low: number;
  high: number;
  kind: "support" | "resistance";
  touches: number;
  last_touch: string;
  strength: "major" | "minor";
  evidence: string;
}
export interface PriceActionSetup {
  kind: string;
  aggressive_entry: number | null;
  conservative_entry: number | null;
  stop: number | null;
  target_1: number | null;
  target_2: number | null;
  major_target: number | null;
  risk_reward: number | null;
  rationale: string;
}
export interface PriceAction {
  score: number | null;
  bias: "bullish" | "neutral" | "bearish";
  quality: string;
  phase: string;
  phase_confidence: string;
  structure_daily: string;
  structure_weekly: string;
  breakout_status: string;
  components: Record<string, number>;
  zones: PriceActionZone[];
  volume: {
    relative: number | null; label: string; average: number | null;
    trend: string; note: string; verdict: string;
  };
  candles: string[];
  /** Strength against the security's OWN market index. Note this is not `volume.relative`
   *  above, which is relative volume - two different quantities that share a word. */
  relative?: {
    lead_pct: number | null;
    recent_lead_pct: number | null;
    improving: boolean | null;
    score: number | null;
    note: string;
  };
  summary: string;
  what_changes_it: { bullish?: string; bearish?: string; wait?: string };
  notes: string[];
  setup: PriceActionSetup;
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
  /** Optional: company files written before the price-action engine have no such
   *  key, and a required field would be a lie about the data on disk. */
  price_action?: PriceAction | null;
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
  /** Points AVAILABLE per category for that period. Zero means the category did not apply -
   *  a bank has no cash-conversion cycle - and the score renormalises over the rest, which is
   *  why the six marks can add to less than the published score. */
  cats_max?: Record<string, number> | null;
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
  label?: string;
  earned: number;
  /** What this category COULD have earned for this company. Lower than `original_max` when a
   *  metric does not apply to the business model - a bank has no quick ratio - and the score
   *  renormalises over the rest rather than charging the company for the gap. */
  applicable_max: number;
  /** The category's budget before any model exclusions. */
  original_max?: number;
  /** LEGACY. Roughly a quarter of stored company files still carry the older six-category
   *  scorecard, which names this field `points` and publishes no `label`. Those files are
   *  rewritten as each company is next scored, so both shapes are live at once and the
   *  component has to read either. */
  points?: number;
  percent?: number | null;
  scored?: number;
  na_model?: number;
  no_data?: number;
  parts?: Record<string, number | null>;
}
export interface FundamentalScorecard {
  score: number | null;
  grade: string;
  /** How many of the fifteen matrix metrics could be measured, and how many APPLY at all to
   *  this business model. A bank has eleven marked N/A by design, so its score rests on four -
   *  which the page must show, or a 100 on four reads the same as a 100 on fifteen. */
  scored_count?: number | null;
  applicable_count?: number | null;
  metric_total?: number | null;
  model?: string | null;
  model_note?: string | null;
  classification?: string | null;
  categories: Record<string, ScoreCategory>;
  metrics: Record<string, number | null>;
  /** Earnings-quality red flags, e.g. profit not backed by operating cash. */
  flags: string[];
}
