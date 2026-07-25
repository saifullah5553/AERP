// Raw-material cost-trend mapping for the company page.
//
// The backend bakes raw_materials.json: per-commodity trend (from real futures
// moving averages) + a sector→commodity map + an aggregate outlook. Here we attach
// the right commodities to a company by its sector/industry and translate each
// input's trend into a margin impact — a company that *consumes* an input benefits
// when that input's price falls. Deterministic, not a forecast.

import type { CommoditySummary } from "@/lib/research";

export type Trend = "increasing" | "decreasing" | "sideways";

export interface Commodity {
  symbol: string;
  name: string;
  trend: Trend;
  change_pct: number | null;
  close: number | null;
}

export interface RawMaterialsData {
  commodities: Record<string, Commodity>;
  sector_map: { keywords: string[]; materials: string[] }[];
  outlook: string;
  counts: { decreasing: number; increasing: number; sideways: number };
}

export interface MaterialImpact {
  name: string;
  symbol: string;
  trend: Trend;
  changePct: number | null;
  impact: "Positive" | "Neutral" | "Negative";
  effect: string;
}

/** Consumer-side rule: falling input price → positive margin impact. */
function impactFor(trend: Trend): { impact: MaterialImpact["impact"]; effect: string } {
  if (trend === "decreasing")
    return { impact: "Positive", effect: "Lower input cost — supports gross-margin expansion" };
  if (trend === "increasing")
    return { impact: "Negative", effect: "Rising input cost — pressures gross margins" };
  return { impact: "Neutral", effect: "Stable input cost — margins broadly unchanged" };
}

/** Commodities relevant to a company, resolved by sector/industry keywords. */
export function companyMaterials(
  sector: string | null,
  industry: string | null,
  data: RawMaterialsData | null,
): MaterialImpact[] {
  if (!data) return [];
  const hay = `${sector ?? ""} ${industry ?? ""}`.toLowerCase();
  const symbols = new Set<string>();
  for (const entry of data.sector_map) {
    if (entry.keywords.some((k) => hay.includes(k))) {
      for (const m of entry.materials) symbols.add(m);
    }
  }
  const out: MaterialImpact[] = [];
  for (const sym of symbols) {
    const c = data.commodities[sym];
    if (!c) continue;
    const { impact, effect } = impactFor(c.trend);
    out.push({ name: c.name, symbol: sym, trend: c.trend, changePct: c.change_pct, impact, effect });
  }
  return out;
}

export function commoditySummary(materials: MaterialImpact[]): CommoditySummary {
  const hasInputs = materials.length > 0;
  const anyIncreasing = materials.some((m) => m.trend === "increasing");
  const decreasing = materials.filter((m) => m.trend === "decreasing").length;
  return { hasInputs, anyIncreasing, favorable: hasInputs && decreasing > materials.length / 2 };
}
