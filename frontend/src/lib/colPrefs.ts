// Persisted screener column visibility (hidden column ids), so show/hide choices
// survive reloads independently of saved views.

const KEY = "aerp-hidden-cols";

export function loadHiddenCols(): string[] {
  try {
    const v = JSON.parse(localStorage.getItem(KEY) || "[]");
    return Array.isArray(v) ? v : [];
  } catch {
    return [];
  }
}

export function saveHiddenCols(ids: string[]): void {
  try {
    localStorage.setItem(KEY, JSON.stringify(ids));
  } catch {
    /* ignore */
  }
}
