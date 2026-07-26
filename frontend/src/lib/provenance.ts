// Data provenance — honest, per-domain source + confidence for a security.
//
// Sources are deterministic by market/asset class (that's how the pipeline ingests),
// so this is factual reference metadata, not a guess. "Last updated" is the snapshot
// timestamp; confidence reflects source reliability + typical freshness.

export type Confidence = "High" | "Medium" | "Low";

export interface DataSource {
  domain: string;
  source: string;
  confidence: Confidence;
  note?: string;
}

const PSX = "psx";

/** Per-domain sources for a security, by region + asset class. */
export function dataSources(region: string, assetClass: string): DataSource[] {
  const isPsx = region === PSX;
  const isEquity = assetClass === "equity";
  const out: DataSource[] = [];

  // Price & technicals
  out.push({
    domain: "Price & Technicals",
    source: isPsx ? "PSX (dps.psx.com.pk)" : "Yahoo Finance",
    confidence: "High",
    note: "End-of-day OHLCV; indicators computed in-house",
  });

  if (isEquity) {
    out.push({
      domain: "Fundamentals",
      source: isPsx ? "stockanalysis.com (PSX filings)" : "Yahoo Finance",
      confidence: isPsx ? "Medium" : "High",
      note: isPsx ? "Annual statements; may lag latest quarter" : "Annual + quarterly (TTM)",
    });
    out.push({
      domain: "Insider Activity",
      source: isPsx ? "Portfolio360 (exchange filings)" : "Yahoo Finance",
      confidence: "High",
      note: "Open-market insider transactions, 60-day window",
    });
    if (!isPsx) {
      out.push({
        domain: "Analyst Estimates",
        source: "Yahoo Finance",
        confidence: "Medium",
        note: "Consensus EPS/revenue + next earnings date",
      });
    }
    out.push({
      domain: "News",
      source: "Google News",
      confidence: "Medium",
      note: "Headlines matched by company name",
    });
  }

  out.push({
    domain: "Macro & Regime",
    source: isPsx ? "Portfolio360 (SBP/PBS) + World Bank" : "World Bank + index technicals",
    confidence: isPsx ? "High" : "Medium",
    note: isPsx ? "Live PK macro series" : "World Bank annual + index trend",
  });

  return out;
}

export function confidenceTone(c: Confidence): string {
  return c === "High" ? "#22c55e" : c === "Medium" ? "#eab308" : "#f87171";
}
