import "ag-grid-community/styles/ag-grid.css";
import "ag-grid-community/styles/ag-theme-quartz.css";

import type {
  ColDef,
  GridApi,
  GridReadyEvent,
  IDatasource,
  IGetRowsParams,
} from "ag-grid-community";
import { AgGridReact } from "ag-grid-react";
import { useCallback, useEffect, useMemo, useRef } from "react";

import { api } from "@/lib/api";
import type { ScreenerQuery, ScreenerRow } from "@/types/api";
import { buildColumnDefs } from "./columns";

const PAGE_SIZE = 50;

type Filters = Omit<ScreenerQuery, "page" | "page_size" | "sort_by" | "sort_dir">;

interface Props {
  filters: Filters;
  onGridReady?: (api: GridApi<ScreenerRow>) => void;
  onTotal?: (total: number) => void;
  onRowClick?: (row: ScreenerRow) => void;
}

export default function ScreenerGrid({ filters, onGridReady, onTotal, onRowClick }: Props) {
  const gridApiRef = useRef<GridApi<ScreenerRow> | null>(null);
  const filtersRef = useRef<Filters>(filters);
  filtersRef.current = filters;

  const columnDefs = useMemo<ColDef<ScreenerRow>[]>(() => buildColumnDefs(), []);
  const defaultColDef = useMemo<ColDef>(
    () => ({ resizable: true, sortable: false, suppressHeaderMenuButton: true, filter: false }),
    [],
  );

  const datasource = useMemo<IDatasource>(
    () => ({
      rowCount: undefined,
      getRows: (p: IGetRowsParams) => {
        const q = filtersRef.current;
        const pageSize = p.endRow - p.startRow || PAGE_SIZE;
        const page = Math.floor(p.startRow / pageSize) + 1;
        const sort = p.sortModel[0];
        api
          .screener({
            page,
            page_size: pageSize,
            ...q,
            sort_by: sort?.colId,
            sort_dir: sort?.sort as "asc" | "desc" | undefined,
          })
          .then((res) => {
            onTotal?.(res.total);
            const lastRow = page * pageSize >= res.total ? res.total : -1;
            p.successCallback(res.items, lastRow === -1 ? undefined : lastRow);
          })
          .catch(() => p.failCallback());
      },
    }),
    [onTotal],
  );

  // Reload from the first block whenever the filters change.
  useEffect(() => {
    gridApiRef.current?.purgeInfiniteCache();
  }, [filters]);

  const handleGridReady = useCallback(
    (e: GridReadyEvent<ScreenerRow>) => {
      gridApiRef.current = e.api;
      onGridReady?.(e.api);
    },
    [onGridReady],
  );

  return (
    <div className="ag-theme-quartz-dark h-full w-full">
      <AgGridReact<ScreenerRow>
        columnDefs={columnDefs}
        defaultColDef={defaultColDef}
        rowModelType="infinite"
        datasource={datasource}
        cacheBlockSize={PAGE_SIZE}
        maxBlocksInCache={20}
        blockLoadDebounceMillis={150}
        rowHeight={34}
        headerHeight={38}
        animateRows={false}
        onGridReady={handleGridReady}
        onRowClicked={(e) => e.data && onRowClick?.(e.data)}
        suppressCellFocus
      />
    </div>
  );
}
