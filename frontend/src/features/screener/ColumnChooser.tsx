import type { GridApi } from "ag-grid-community";
import { useState } from "react";

import { loadHiddenCols, saveHiddenCols } from "@/lib/colPrefs";

interface Col {
  id: string;
  name: string;
  visible: boolean;
}

// Community-friendly column show/hide dropdown (the AG-Grid tool panel is Enterprise).
// Toggles visibility via the grid API and persists hidden columns to localStorage.
export default function ColumnChooser({ getApi }: { getApi: () => GridApi | null }) {
  const [open, setOpen] = useState(false);
  const [cols, setCols] = useState<Col[]>([]);

  const refresh = () => {
    const api = getApi();
    if (!api) return;
    const list = (api.getColumns() ?? []).map((c) => ({
      id: c.getColId(),
      name: String(c.getColDef().headerName ?? c.getColId()),
      visible: c.isVisible(),
    }));
    setCols(list);
  };

  const openMenu = () => {
    refresh();
    setOpen(true);
  };

  const toggle = (id: string, visible: boolean) => {
    const api = getApi();
    if (!api) return;
    api.setColumnsVisible([id], visible);
    const hidden = new Set(loadHiddenCols());
    if (visible) hidden.delete(id);
    else hidden.add(id);
    saveHiddenCols([...hidden]);
    refresh();
  };

  const showAll = () => {
    const api = getApi();
    if (!api) return;
    const ids = (api.getColumns() ?? []).map((c) => c.getColId());
    api.setColumnsVisible(ids, true);
    saveHiddenCols([]);
    refresh();
  };

  return (
    <div className="relative inline-block">
      <button
        onClick={() => (open ? setOpen(false) : openMenu())}
        className="rounded bg-base-700 px-3 py-1 text-slate-200 hover:bg-base-600"
      >
        Columns ▾
      </button>
      {open && (
        <>
          <div className="fixed inset-0 z-20" onClick={() => setOpen(false)} />
          <div className="absolute left-0 z-30 mt-1 max-h-[60vh] w-56 overflow-y-auto rounded-lg border border-base-500 bg-base-800 shadow-2xl">
            <div className="sticky top-0 flex items-center justify-between border-b border-base-600 bg-base-800 px-3 py-2">
              <span className="text-[11px] font-bold uppercase tracking-wide text-slate-300">Columns</span>
              <button onClick={showAll} className="text-[10px] font-semibold text-accent hover:underline">
                Show all
              </button>
            </div>
            <div className="py-1">
              {cols.map((c) => (
                <label
                  key={c.id}
                  className="flex cursor-pointer items-center gap-2 px-3 py-1.5 text-xs text-slate-200 hover:bg-base-700/50"
                >
                  <input
                    type="checkbox"
                    checked={c.visible}
                    onChange={(e) => toggle(c.id, e.target.checked)}
                    className="accent-accent"
                  />
                  <span>{c.name}</span>
                </label>
              ))}
            </div>
          </div>
        </>
      )}
    </div>
  );
}
