import type { ColumnState } from "ag-grid-community";

import type { ScreenerQuery } from "@/types/api";

// A saved view captures the filter/sort query plus the AG Grid column layout
// (order, width, pin, visibility, sort), persisted to localStorage.
export interface SavedView {
  name: string;
  query: Partial<ScreenerQuery>;
  columnState: ColumnState[];
}

const KEY = "aerp.savedViews.v1";

export function loadViews(): SavedView[] {
  try {
    const raw = localStorage.getItem(KEY);
    return raw ? (JSON.parse(raw) as SavedView[]) : [];
  } catch {
    return [];
  }
}

export function saveView(view: SavedView): SavedView[] {
  const views = loadViews().filter((v) => v.name !== view.name);
  views.push(view);
  localStorage.setItem(KEY, JSON.stringify(views));
  return views;
}

export function deleteView(name: string): SavedView[] {
  const views = loadViews().filter((v) => v.name !== name);
  localStorage.setItem(KEY, JSON.stringify(views));
  return views;
}
