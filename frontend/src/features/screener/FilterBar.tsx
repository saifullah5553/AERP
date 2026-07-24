import { useEffect, useState } from "react";

import type { AssetClass, MarketRegion, ScreenerQuery } from "@/types/api";

type Filters = Omit<ScreenerQuery, "page" | "page_size" | "sort_by" | "sort_dir">;

const REGIONS: { value: MarketRegion | "all"; label: string }[] = [
  { value: "all", label: "All Markets" },
  { value: "us", label: "US" },
  { value: "psx", label: "Pakistan" },
  { value: "india", label: "India" },
  { value: "gcc", label: "GCC" },
  { value: "global", label: "Global" },
];

const ASSET_CLASSES: { value: AssetClass | ""; label: string }[] = [
  { value: "", label: "All Assets" },
  { value: "equity", label: "Equity" },
  { value: "crypto", label: "Crypto" },
  { value: "forex", label: "Forex" },
  { value: "commodity", label: "Commodity" },
  { value: "etf", label: "ETF" },
  { value: "index", label: "Index" },
];

interface Props {
  filters: Filters;
  onChange: (next: Filters) => void;
}

export default function FilterBar({ filters, onChange }: Props) {
  const [search, setSearch] = useState(filters.search ?? "");

  // Debounce the free-text search so we don't hit the API on every keystroke.
  useEffect(() => {
    const t = setTimeout(() => {
      onChange({ ...filters, search: search || undefined });
    }, 300);
    return () => clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [search]);

  const activeRegion = filters.region ?? "all";

  return (
    <div className="flex flex-wrap items-end gap-3 border-b border-base-600 bg-base-800 px-4 py-3">
      <div className="flex flex-wrap gap-1">
        {REGIONS.map((r) => (
          <button
            key={r.value}
            onClick={() =>
              onChange({ ...filters, region: r.value === "all" ? undefined : (r.value as MarketRegion) })
            }
            className={`rounded px-3 py-1.5 text-sm font-medium transition-colors ${
              activeRegion === r.value
                ? "bg-accent-muted text-white"
                : "bg-base-700 text-slate-300 hover:bg-base-600"
            }`}
          >
            {r.label}
          </button>
        ))}
      </div>

      <div className="flex flex-col gap-1">
        <label className="text-[10px] font-semibold uppercase tracking-wide text-slate-400">
          Search
        </label>
        <input
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Ticker or company…"
          className="w-56 rounded border border-base-500 bg-base-900 px-3 py-1.5 text-sm outline-none focus:border-accent"
        />
      </div>

      <div className="flex flex-col gap-1">
        <label className="text-[10px] font-semibold uppercase tracking-wide text-slate-400">
          Asset Class
        </label>
        <select
          value={filters.asset_class ?? ""}
          onChange={(e) =>
            onChange({ ...filters, asset_class: (e.target.value || undefined) as AssetClass | undefined })
          }
          className="rounded border border-base-500 bg-base-900 px-3 py-1.5 text-sm outline-none focus:border-accent"
        >
          {ASSET_CLASSES.map((a) => (
            <option key={a.value} value={a.value}>
              {a.label}
            </option>
          ))}
        </select>
      </div>

      <div className="flex flex-col gap-1">
        <label className="text-[10px] font-semibold uppercase tracking-wide text-slate-400">
          Sector
        </label>
        <input
          value={filters.sector ?? ""}
          onChange={(e) => onChange({ ...filters, sector: e.target.value || undefined })}
          placeholder="e.g. Technology"
          className="w-44 rounded border border-base-500 bg-base-900 px-3 py-1.5 text-sm outline-none focus:border-accent"
        />
      </div>

      <div className="flex flex-col gap-1">
        <label className="text-[10px] font-semibold uppercase tracking-wide text-slate-400">
          Min Composite: <span className="text-accent">{filters.min_composite ?? 0}</span>
        </label>
        <input
          type="range"
          min={0}
          max={100}
          value={filters.min_composite ?? 0}
          onChange={(e) =>
            onChange({ ...filters, min_composite: Number(e.target.value) || undefined })
          }
          className="w-44 accent-accent"
        />
      </div>
    </div>
  );
}
