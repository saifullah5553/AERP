import { useState } from "react";

import { getTheme, setTheme, type Theme } from "@/lib/theme";

// Small dark/light switch. Theme lives on <html data-theme> + localStorage, so it
// persists across pages and reloads.
export default function ThemeToggle() {
  const [theme, setThemeState] = useState<Theme>(() => getTheme());

  const toggle = () => {
    const next: Theme = theme === "dark" ? "light" : "dark";
    setTheme(next);
    setThemeState(next);
  };

  return (
    <button
      onClick={toggle}
      title={`Switch to ${theme === "dark" ? "light" : "dark"} theme`}
      className="flex items-center gap-1.5 rounded-full border border-base-500 bg-base-700 px-2.5 py-1 text-xs font-semibold text-slate-300 transition-colors hover:bg-base-600"
    >
      <span className="text-sm leading-none">{theme === "dark" ? "☀️" : "🌙"}</span>
      <span>{theme === "dark" ? "Light" : "Dark"}</span>
    </button>
  );
}
