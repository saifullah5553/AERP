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

/** "Jun 26" - the quarter END, which is what the statement is dated. */
function quarterLabel(key: string): string {
  const [year, q] = key.split("-Q");
  const month = ["Mar", "Jun", "Sep", "Dec"][Number(q) - 1] ?? "";
  return `${month} ${year.slice(2)}`;
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
    colId: `q_${key}`,
    headerName: quarterLabel(key),
    headerTooltip: `Fundamental score for the trailing twelve months ended ${quarterLabel(key)}`,
    width: 78,
    sortable: false,
    cellRenderer: QuarterScoreCell,
    cellRendererParams: { quarterKey: key },
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
    {
      field: "quality_score",
      headerName: "Fund Score",
      headerTooltip:
        "Fundamental score: growth 35% + profitability 15% (gross/operating/net margin, ROIC) + cash 25% " +
        "(operating CF, free CF, earnings backed by cash) + solvency & liquidity 25% " +
        "(net debt/EBITDA, interest cover, D/E, current and quick ratios). " +
        "Business quality only - price is a separate question.",
      width: 110,
      sort: "desc",
      sortable: true,
      cellRenderer: ScoreCell,
      cellStyle: heat,
    },
    {
      field: "quality_trend",
      headerName: "Trend",
      headerTooltip:
        "Direction of the fundamental score across its trailing-twelve-month history.",
      width: 110,
      sortable: true,
      cellRenderer: TrendCell,
    },
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
