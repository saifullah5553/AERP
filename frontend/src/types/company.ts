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
}
