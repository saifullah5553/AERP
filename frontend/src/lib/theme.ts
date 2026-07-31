// Light/dark theme, persisted in localStorage and applied via a data-theme attribute
// on <html> (index.css defines the palette for each). Default = dark.

export type Theme = "dark" | "light";
const KEY = "aerp-theme";

export function getTheme(): Theme {
  try {
    return localStorage.getItem(KEY) === "light" ? "light" : "dark";
  } catch {
    return "dark";
  }
}

export function applyTheme(t: Theme): void {
  document.documentElement.dataset.theme = t;
}

export function setTheme(t: Theme): void {
  try {
    localStorage.setItem(KEY, t);
  } catch {
    /* ignore (private mode) */
  }
  applyTheme(t);
}

export function initTheme(): void {
  applyTheme(getTheme());
}
