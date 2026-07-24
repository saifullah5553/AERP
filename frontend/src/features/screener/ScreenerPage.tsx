import type { GridApi } from "ag-grid-community";
import { useCallback, useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";

import { api } from "@/lib/api";
import { exportScreenerCsv } from "@/lib/exportCsv";
import { openQuoteStream } from "@/lib/liveQuotes";
import {
  deleteView,
  loadViews,
  saveView,
  type SavedView,
} from "@/lib/savedViews";
import type { ScreenerQuery, ScreenerRow } from "@/types/api";
import FilterBar from "./FilterBar";
import ScreenerGrid from "./ScreenerGrid";

type Filters = Omit<ScreenerQuery, "page" | "page_size" | "sort_by" | "sort_dir">;

export default function ScreenerPage() {
  const [filters, setFilters] = useState<Filters>({});
  const [total, setTotal] = useState<number | null>(null);
  const [views, setViews] = useState<SavedView[]>(() => loadViews());
  const [online, setOnline] = useState<boolean | null>(null);
  const [exporting, setExporting] = useState(false);
  const gridApiRef = useRef<GridApi<ScreenerRow> | null>(null);
  const navigate = useNavigate();

  const [live, setLive] = useState(false);

  useEffect(() => {
    const ctrl = new AbortController();
    api
      .health(ctrl.signal)
      .then(() => setOnline(true))
      .catch(() => setOnline(false));
    return () => ctrl.abort();
  }, []);

  // Live prices: update loaded grid rows in place as ticks arrive.
  useEffect(() => {
    return openQuoteStream({
      onOpen: () => setLive(true),
      onError: () => setLive(false),
      onQuote: (q) => {
        const gridApi = gridApiRef.current;
        if (!gridApi) return;
        gridApi.forEachNode((node) => {
          if (node.data?.provider_symbol !== q.symbol) return;
          if (q.price !== null) node.setDataValue("price", q.price);
          if (q.change_pct !== null) node.setDataValue("change_pct", q.change_pct);
          gridApi.flashCells({ rowNodes: [node], columns: ["price", "change_pct"] });
        });
      },
    });
  }, []);

  const handleSaveView = useCallback(() => {
    const name = window.prompt("Save current view as:");
    if (!name || !gridApiRef.current) return;
    setViews(saveView({ name, query: filters, columnState: gridApiRef.current.getColumnState() }));
  }, [filters]);

  const handleLoadView = useCallback((name: string) => {
    const view = loadViews().find((v) => v.name === name);
    if (!view) return;
    setFilters(view.query as Filters);
    gridApiRef.current?.applyColumnState({ state: view.columnState, applyOrder: true });
  }, []);

  const handleExport = useCallback(async () => {
    setExporting(true);
    try {
      await exportScreenerCsv(filters);
    } finally {
      setExporting(false);
    }
  }, [filters]);

  return (
    <div className="flex h-full flex-col">
      <header className="flex items-center justify-between border-b border-base-600 bg-base-900 px-4 py-2.5">
        <div className="flex items-baseline gap-3">
          <span className="text-lg font-bold tracking-tight text-accent">AERP</span>
          <span className="text-sm text-slate-400">Equity Research Terminal</span>
          {total !== null && (
            <span className="rounded bg-base-700 px-2 py-0.5 text-xs text-slate-300">
              {total.toLocaleString()} securities
            </span>
          )}
        </div>
        <div className="flex items-center gap-3 text-xs">
          {live && (
            <span className="flex items-center gap-1.5 font-semibold text-up">
              <span className="h-2 w-2 animate-pulse rounded-full bg-up" />
              LIVE
            </span>
          )}
          <span className="flex items-center gap-1.5 text-slate-400">
            <span
              className={`h-2 w-2 rounded-full ${
                online === null ? "bg-slate-500" : online ? "bg-up" : "bg-down"
              }`}
            />
            {online === null ? "connecting" : online ? "API online" : "API offline"}
          </span>
        </div>
      </header>

      <FilterBar filters={filters} onChange={setFilters} />

      <div className="flex items-center gap-2 border-b border-base-600 bg-base-800 px-4 py-2 text-xs">
        <button
          onClick={handleExport}
          disabled={exporting}
          className="rounded bg-base-700 px-3 py-1 text-slate-200 hover:bg-base-600 disabled:opacity-50"
        >
          {exporting ? "Exporting…" : "Export CSV"}
        </button>
        <button
          onClick={handleSaveView}
          className="rounded bg-base-700 px-3 py-1 text-slate-200 hover:bg-base-600"
        >
          Save View
        </button>
        <select
          onChange={(e) => e.target.value && handleLoadView(e.target.value)}
          value=""
          className="rounded border border-base-500 bg-base-900 px-2 py-1 text-slate-200"
        >
          <option value="">Load view…</option>
          {views.map((v) => (
            <option key={v.name} value={v.name}>
              {v.name}
            </option>
          ))}
        </select>
        {views.length > 0 && (
          <button
            onClick={() => {
              const name = window.prompt("Delete which view? Enter its exact name:");
              if (name) setViews(deleteView(name));
            }}
            className="rounded bg-base-700 px-3 py-1 text-slate-400 hover:bg-base-600"
          >
            Delete View
          </button>
        )}
        <button
          onClick={() => gridApiRef.current?.resetColumnState()}
          className="rounded bg-base-700 px-3 py-1 text-slate-400 hover:bg-base-600"
        >
          Reset Columns
        </button>
      </div>

      <div className="min-h-0 flex-1">
        <ScreenerGrid
          filters={filters}
          onTotal={setTotal}
          onGridReady={(gridApi) => (gridApiRef.current = gridApi)}
          onRowClick={(row) => navigate(`/company/${encodeURIComponent(row.provider_symbol)}`)}
        />
      </div>
    </div>
  );
}
