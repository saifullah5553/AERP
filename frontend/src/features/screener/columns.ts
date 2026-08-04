import type { ColDef } from "ag-grid-community";

import { fmtInt, fmtNumber, fmtPercent, scoreHeatBg, titleize } from "@/lib/format";
import type { ScreenerRow } from "@/types/api";
import {
  ActionCell,
  ChangeCell,
  PatternCell,
  ScoreCell,
  ScoreHistoryCell,
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
      // The arc matters more than today's number: a 70 on the way up and a 70 on the way down
      // are different businesses, and a single score cannot tell them apart.
      field: "score_history",
      headerName: "Score by Quarter (TTM)",
      headerTooltip:
        "The fundamental score at each quarter-end, newest first, with the move against the " +
        "prior quarter. Every point is a full trailing twelve months, so seasonality cannot " +
        "masquerade as a trend. Hover for all 20 quarters.",
      width: 290,
      sortable: false,
      cellRenderer: ScoreHistoryCell,
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
