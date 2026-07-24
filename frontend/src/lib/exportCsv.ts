import { api } from "@/lib/api";
import type { ScreenerQuery, ScreenerRow } from "@/types/api";

const EXPORT_COLUMNS: (keyof ScreenerRow)[] = [
  "symbol", "name", "market_code", "sector", "industry", "price", "change_pct",
  "volume", "market_cap", "pe_ttm", "roe", "debt_to_equity", "revenue_growth",
  "eps_growth", "dividend_yield", "technical_score", "fundamental_score",
  "composite_score", "top_pattern", "signal",
];

function csvCell(v: unknown): string {
  if (v === null || v === undefined) return "";
  const s = String(v);
  return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
}

// Pages through the API (bounded) so the export reflects the full filtered set,
// not just the rows currently loaded in the grid's infinite cache.
export async function exportScreenerCsv(
  query: Omit<ScreenerQuery, "page" | "page_size">,
  maxRows = 5000,
): Promise<void> {
  const pageSize = 500;
  const rows: ScreenerRow[] = [];
  for (let page = 1; rows.length < maxRows; page++) {
    const res = await api.screener({ ...query, page, page_size: pageSize });
    rows.push(...res.items);
    if (res.items.length < pageSize || rows.length >= res.total) break;
  }

  const header = EXPORT_COLUMNS.join(",");
  const lines = rows
    .slice(0, maxRows)
    .map((r) => EXPORT_COLUMNS.map((c) => csvCell(r[c])).join(","));
  const blob = new Blob([[header, ...lines].join("\n")], {
    type: "text/csv;charset=utf-8;",
  });

  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `aerp-screener-${new Date().toISOString().slice(0, 10)}.csv`;
  a.click();
  URL.revokeObjectURL(url);
}
