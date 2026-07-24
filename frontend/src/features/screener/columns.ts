import type { ColDef } from "ag-grid-community";

import { fmtCompact, fmtInt, fmtNumber, fmtPercent, titleize } from "@/lib/format";
import type { ScreenerRow } from "@/types/api";
import { ChangeCell, PatternCell, ScoreCell, SignalCell } from "./cells";

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
    { field: "industry", headerName: "Industry", width: 170, sortable: false },

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
    num("market_cap", "Mkt Cap", { width: 120, valueFormatter: (p) => fmtCompact(p.value) }),

    num("pe_ttm", "P/E", { width: 90, valueFormatter: (p) => fmtNumber(p.value) }),
    num("roe", "ROE", { width: 90, valueFormatter: (p) => fmtPercent(p.value) }),
    num("debt_to_equity", "D/E", { width: 90, valueFormatter: (p) => fmtNumber(p.value) }),
    num("revenue_growth", "Rev Gr", { width: 100, valueFormatter: (p) => fmtPercent(p.value) }),
    num("eps_growth", "EPS Gr", { width: 100, valueFormatter: (p) => fmtPercent(p.value) }),
    num("dividend_yield", "Div Y", { width: 90, valueFormatter: (p) => fmtPercent(p.value) }),

    {
      field: "technical_score",
      headerName: "Tech",
      width: 90,
      sortable: true,
      cellRenderer: ScoreCell,
    },
    {
      field: "fundamental_score",
      headerName: "Fund",
      width: 90,
      sortable: true,
      cellRenderer: ScoreCell,
    },
    {
      field: "composite_score",
      headerName: "Composite",
      width: 120,
      sort: "desc",
      sortable: true,
      cellRenderer: ScoreCell,
    },
    {
      field: "top_pattern",
      headerName: "Pattern",
      width: 160,
      sortable: false,
      cellRenderer: PatternCell,
      valueFormatter: (p) => titleize(p.value),
    },
    {
      field: "insider_score",
      headerName: "Insider",
      width: 90,
      sortable: false,
      cellRenderer: ScoreCell,
    },
    {
      field: "insider_activity",
      headerName: "Insider Act.",
      width: 120,
      sortable: false,
      valueFormatter: (p) => titleize(p.value),
    },
    {
      field: "signal",
      headerName: "Signal",
      width: 130,
      sortable: false,
      cellRenderer: SignalCell,
    },
  ];
}
