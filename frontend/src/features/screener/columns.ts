import type { ColDef } from "ag-grid-community";

import { fmtInt, fmtNumber, fmtPercent, scoreHeatBg, titleize } from "@/lib/format";
import type { ScreenerRow } from "@/types/api";
import {
  ActionCell,
  ChangeCell,
  PatternCell,
  QuarterScoreCell,
  ScoreCell,
  TrendCell,
} from "./cells";

// Translucent heat fill for a score column cell.
const heat = (p: { value: unknown }) => ({
  backgroundColor: scoreHeatBg(typeof p.value === "number" ? p.value : null),
});

// Fields the backend can sort on (app/services/screener.py SORT_FIELDS).
const SERVER_SORTABLE = new Set([
  "symbol", "name", "market_cap", "price", "change_pct", "volume",
  "pe_ttm", "roe", "debt_to_equity", "revenue_growth", "eps_growth",
  "dividend_yield", "fundamental_score", "technical_score", "composite_score",
]);

function num(field: keyof ScreenerRow, header: string, opts: Partial<ColDef> = {}): ColDef {
  return {
    field: field as string,
    headerName: header,
    sortable: SERVER_SORTABLE.has(field as string),
    type: "rightAligned",
    cellClass: "num",
    ...opts,
  };
}

/** Calendar quarter key for a period-end date: "2026-Q2". */
export function quarterKey(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  return `${d.getFullYear()}-Q${Math.floor(d.getMonth() / 3) + 1}`;
}

/** "Jun 26" - the period END, which is what the statement is dated. */
function quarterLabel(key: string): string {
  const [year, q] = key.split("-Q");
  const month = ["Mar", "Jun", "Sep", "Dec"][Number(q) - 1] ?? "";
  return `${month} ${year.slice(2)}`;
}

/** "2026-Q2" -> "q_2026Q2", the row field holding that quarter's score. */
function quarterField(key: string): string {
  return `q_${key.replace("-", "")}`;
}

/**
 * The twelve-month window a column covers, spelled out: "Apr 25 - Mar 26".
 *
 * The header alone reads like a quarter, and every figure here is a TRAILING TWELVE MONTHS
 * score - "Mar 26" is the year to 31 Mar 26, not the Jan-Mar quarter. Reading it as three
 * months would misinterpret every number in the row, so the window is stated rather than
 * implied.
 */
function quarterWindow(key: string): string {
  const [yearStr, q] = key.split("-Q");
  const year = Number(yearStr);
  const endMonth = Number(q) * 3;                    // 3, 6, 9, 12
  const startMonth = (endMonth % 12) + 1;            // the month after, a year earlier
  const startYear = endMonth === 12 ? year : year - 1;
  const names = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
                 "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  const two = (y: number) => String(y).slice(2);
  return `${names[startMonth - 1]} ${two(startYear)} - ${names[endMonth - 1]} ${two(year)}`;
}

/**
 * The last `count` calendar quarters, newest first.
 *
 * Derived from the calendar rather than from the loaded rows because the grid pages its data in
 * - there is no complete row set to inspect when the columns are built. Companies whose fiscal
 * year ends off-calendar still land in the quarter their period end falls in.
 */
function recentQuarters(count: number): string[] {
  const now = new Date();
  let year = now.getFullYear();
  // Start at the last COMPLETED quarter. The current one has not ended, so nobody has reported
  // it - leading with it would put an empty column in front of every company.
  let q = Math.floor(now.getMonth() / 3);
  if (q === 0) {
    q = 4;
    year -= 1;
  }
  const out: string[] = [];
  for (let i = 0; i < count; i++) {
    out.push(`${year}-Q${q}`);
    q -= 1;
    if (q === 0) {
      q = 4;
      year -= 1;
    }
  }
  return out;
}

/** One column per quarter: that quarter's fundamental score, and the move against the prior one. */
function quarterColumns(): ColDef<ScreenerRow>[] {
  return recentQuarters(20).map((key) => ({
    // colId must equal the row field: the grid sends the sorted column's id as sort_by, and the
    // sort reads that field directly. A mismatch sorts by nothing, silently.
    colId: quarterField(key),
    field: quarterField(key) as keyof ScreenerRow,
    headerName: quarterLabel(key),
    headerTooltip:
      `Fundamental score for the TWELVE MONTHS ended ${quarterLabel(key)} ` +
      `(${quarterWindow(key)}) - not the quarter alone`,
    width: 78,
    sortable: true,
    cellRenderer: QuarterScoreCell,
    cellRendererParams: { quarterKey: key },
  }));
}

/** The six scoring categories, with the budget each is marked out of. */
const CATEGORIES: { key: string; label: string; outOf: number; tip: string }[] = [
  { key: "growth", label: "Grw", outOf: 20, tip: "Growth & growth quality" },
  { key: "profitability", label: "Prof", outOf: 20, tip: "Profitability, margins and returns (incl. ROIC)" },
  { key: "cash_flow", label: "Cash", outOf: 25, tip: "Cash flow & earnings quality - the heaviest category" },
  { key: "balance_sheet", label: "BS", outOf: 15, tip: "Balance sheet, leverage and its servicing" },
  { key: "liquidity", label: "Liq", outOf: 10, tip: "Liquidity & cash reserves, relative to obligations" },
  { key: "working_capital", label: "WC", outOf: 10, tip: "Working capital & capital efficiency" },
];

/** One column per scoring category, showing the newest period's mark out of its budget. */
function categoryColumns(): ColDef<ScreenerRow>[] {
  return CATEGORIES.map((c) => ({
    colId: `cat_${c.key}`,
    headerName: `${c.label} /${c.outOf}`,
    headerTooltip: `${c.tip}. Marked out of ${c.outOf} for the latest TTM period.`,
    width: 84,
    sortable: true,
    // Read out of the nested object rather than a flat field: six more top-level keys on
    // every one of 11,000 rows is weight the file does not need to carry.
    valueGetter: (p) => p.data?.score_cats?.[c.key] ?? null,
    valueFormatter: (p) => (p.value == null ? "—" : p.value.toFixed(1)),
    cellStyle: (p: { value: unknown }) => ({
      backgroundColor:
        typeof p.value === "number" ? scoreHeatBg((p.value / c.outOf) * 100) : undefined,
    }),
  }));
}

export function buildColumnDefs(): ColDef<ScreenerRow>[] {
  return [
    {
      field: "symbol",
      headerName: "Ticker",
      pinned: "left",
      width: 110,
      sortable: true,
      cellClass: "font-semibold text-accent",
    },
    { field: "name", headerName: "Company", width: 220, sortable: true },
    { field: "market_code", headerName: "Exchange", width: 110, sortable: false },
    { field: "sector", headerName: "Sector", width: 150, sortable: false },

    num("price", "Price", { width: 110, valueFormatter: (p) => fmtNumber(p.value) }),
    {
      field: "change_pct",
      headerName: "Chg %",
      width: 100,
      sortable: true,
      type: "rightAligned",
      cellRenderer: ChangeCell,
    },
    num("volume", "Volume", { width: 120, valueFormatter: (p) => fmtInt(p.value) }),

    num("pe_ttm", "P/E", { width: 90, valueFormatter: (p) => fmtNumber(p.value) }),
    num("roe", "ROE", { width: 90, valueFormatter: (p) => fmtPercent(p.value) }),
    num("debt_to_equity", "D/E", { width: 90, valueFormatter: (p) => fmtNumber(p.value) }),
    num("revenue_growth", "Rev Gr", { width: 100, valueFormatter: (p) => fmtPercent(p.value) }),
    num("eps_growth", "EPS Gr", { width: 100, valueFormatter: (p) => fmtPercent(p.value) }),
    num("dividend_yield", "Div Y", { width: 90, valueFormatter: (p) => fmtPercent(p.value) }),

    // Strategy engine first: the point-in-time backtests showed the fundamental quality gate
    // carries the edge (beat the typical stock by +47pp to +65pp across two markets), while
    // technical inputs measured negative. So Action and Quality lead, and Tech is demoted.
    {
      field: "strategy_action",
      headerName: "Action",
      headerTooltip:
        "Quality gate + price action: BUY (strong/improving and starting to move), HOLD, " +
        "WATCH (quality, awaiting a move), AVOID (fails the fundamental gate)",
      width: 110,
      sortable: true,
      cellRenderer: ActionCell,
    },
    // No standalone "Fund Score" column: the headline score IS the newest quarter, so it
    // repeated whichever quarter column that company last reported. The grid still OPENS
    // ranked by it (lib/api.ts sorts on quality_score when no column is sorted) - the
    // duplicate display is what went, not the ordering.
    {
      field: "quality_trend",
      headerName: "Trend",
      headerTooltip:
        "Direction of the fundamental score across its trailing-twelve-month history.",
      width: 110,
      sortable: true,
      cellRenderer: TrendCell,
    },
    // Where the newest score sits in the company's OWN five-year range. Sorting the grid by
    // percentile finds the companies at their personal best or worst, which the raw score
    // cannot: 62 is a recovery for one business and a collapse for another.
    num("score_percentile", "vs Own", {
      width: 92,
      headerTooltip:
        "Percentile of the latest fundamental score within this company's own TTM history. " +
        "100 = its best period on record.",
      valueFormatter: (p) => (p.value == null ? "—" : `${Math.round(p.value)}%`),
    }),
    num("score_avg", "Avg", {
      width: 84,
      headerTooltip: "Mean fundamental score across the stored TTM history.",
      valueFormatter: (p) => fmtNumber(p.value),
    }),
    // The six category marks behind the newest score. A total of 62 can be strong cash flow
    // carrying weak growth or the reverse, and those are different companies.
    ...categoryColumns(),
    ...quarterColumns(),
    {
      field: "technical_score",
      headerName: "Tech",
      headerTooltip:
        "Technical score. Kept for reference only - measured as a negative predictor over " +
        "60 days, so it no longer drives the ranking.",
      width: 90,
      sortable: true,
      cellRenderer: ScoreCell,
      cellStyle: heat,
    },
    {
      field: "top_candlestick",
      headerName: "Candlestick",
      width: 150,
      sortable: false,
      cellRenderer: PatternCell,
      valueFormatter: (p) => titleize(p.value),
    },
    {
      field: "top_chart_pattern",
      headerName: "Chart Pattern",
      width: 160,
      sortable: false,
      cellRenderer: PatternCell,
      valueFormatter: (p) => titleize(p.value),
    },
  ];
}
