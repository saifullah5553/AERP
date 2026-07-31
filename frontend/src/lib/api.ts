import type {
  CatalystsData,
  MacroRegimeData,
  MarketPulse,
  Page,
  ScreenerQuery,
  ScreenerRow,
  SectorStatsData,
  SnapshotMeta,
  SwingRow,
} from "@/types/api";
import type { CompanyDetail } from "@/types/company";
import type { RawMaterialsData } from "@/lib/rawMaterials";

export interface Mover {
  provider_symbol: string;
  symbol: string;
  name: string | null;
  region: string;
  composite: number;
  prev: number;
  delta: number;
  fundamental: number | null;
  technical: number | null;
  date: string;
}
export interface MoversData {
  generated_at: string | null;
  upgrades: Mover[];
  downgrades: Mover[];
}

export interface CotData {
  label: string;
  contract: string;
  report_date: string;
  nc_long: number;
  nc_short: number;
  net: number;
  pct_long: number | null;
  oi: number | null;
  stance: string; // Net Long / Net Short / Flat
  flow: string; // Buying / Selling / Neutral
  net_trend: string;
  oi_trend: string;
}

export interface ExtraIndex {
  provider_symbol: string;
  symbol: string;
  name: string | null;
  region: string;
  price: number | null;
  change_pct: number | null;
}

const BASE = (import.meta.env.VITE_API_BASE ?? "").replace(/\/$/, "");
const V1 = `${BASE}/api/v1`;

// With no API base configured we run in STATIC mode: the app serves a real data
// snapshot (baked into /data/*.json at build time) with no backend — used for the
// GitHub Pages demo. Filtering/sorting/pagination happen client-side.
export const IS_STATIC = BASE === "";
const DATA_BASE = `${import.meta.env.BASE_URL}data`;

function qs(params: Record<string, unknown>): string {
  const sp = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v !== undefined && v !== null && v !== "") sp.set(k, String(v));
  }
  const s = sp.toString();
  return s ? `?${s}` : "";
}

async function getJson<T>(url: string, signal?: AbortSignal): Promise<T> {
  const res = await fetch(url, { signal, headers: { Accept: "application/json" } });
  if (!res.ok) throw new Error(`API ${res.status} ${res.statusText} for ${url}`);
  return (await res.json()) as T;
}

// ── Static-mode helpers ───────────────────────────────────────
let _rowsCache: Promise<ScreenerRow[]> | null = null;
function staticRows(): Promise<ScreenerRow[]> {
  if (!_rowsCache) _rowsCache = getJson<ScreenerRow[]>(`${DATA_BASE}/screener.json`);
  return _rowsCache;
}

function num(v: unknown): number | null {
  return typeof v === "number" ? v : null;
}

function applyScreener(all: ScreenerRow[], q: ScreenerQuery): Page<ScreenerRow> {
  let rows = all;
  if (q.search) {
    const t = q.search.toLowerCase();
    rows = rows.filter(
      (r) => r.symbol.toLowerCase().includes(t) || (r.name ?? "").toLowerCase().includes(t),
    );
  }
  if (q.region) rows = rows.filter((r) => r.region === q.region);
  if (q.asset_class) rows = rows.filter((r) => r.asset_class === q.asset_class);
  if (q.sector) rows = rows.filter((r) => r.sector === q.sector);
  if (q.min_composite != null)
    rows = rows.filter((r) => r.composite_score != null && r.composite_score >= q.min_composite!);

  const key = (q.sort_by ?? "composite_score") as keyof ScreenerRow;
  const dir = q.sort_dir === "asc" ? 1 : -1;
  rows = [...rows].sort((a, b) => {
    const av = num(a[key]);
    const bv = num(b[key]);
    if (av == null && bv == null) return a.symbol.localeCompare(b.symbol);
    if (av == null) return 1; // nulls last
    if (bv == null) return -1;
    return av === bv ? a.symbol.localeCompare(b.symbol) : (av - bv) * dir;
  });

  const total = rows.length;
  const start = (q.page - 1) * q.page_size;
  return { items: rows.slice(start, start + q.page_size), total, page: q.page, page_size: q.page_size };
}

export const api = {
  async screener(query: ScreenerQuery, signal?: AbortSignal): Promise<Page<ScreenerRow>> {
    if (IS_STATIC) return applyScreener(await staticRows(), query);
    return getJson<Page<ScreenerRow>>(`${V1}/screener${qs({ ...query })}`, signal);
  },
  company(providerSymbol: string, signal?: AbortSignal): Promise<CompanyDetail> {
    if (IS_STATIC)
      return getJson<CompanyDetail>(`${DATA_BASE}/company/${encodeURIComponent(providerSymbol)}.json`, signal);
    return getJson<CompanyDetail>(`${V1}/company/${encodeURIComponent(providerSymbol)}`, signal);
  },
  pulse(signal?: AbortSignal): Promise<MarketPulse[]> {
    if (IS_STATIC) return getJson<MarketPulse[]>(`${DATA_BASE}/pulse.json`, signal);
    return getJson<MarketPulse[]>(`${V1}/markets/pulse`, signal);
  },
  rawMaterials(signal?: AbortSignal): Promise<RawMaterialsData> {
    return getJson<RawMaterialsData>(`${DATA_BASE}/raw_materials.json`, signal);
  },
  regime(signal?: AbortSignal): Promise<MacroRegimeData> {
    if (IS_STATIC) return getJson<MacroRegimeData>(`${DATA_BASE}/macro_regime.json`, signal);
    return getJson<MacroRegimeData>(`${V1}/markets/regime`, signal);
  },
  sectorStats(signal?: AbortSignal): Promise<SectorStatsData> {
    if (IS_STATIC) return getJson<SectorStatsData>(`${DATA_BASE}/sector_stats.json`, signal);
    return getJson<SectorStatsData>(`${V1}/markets/sectors`, signal);
  },
  swing(signal?: AbortSignal): Promise<SwingRow[]> {
    if (IS_STATIC) return getJson<SwingRow[]>(`${DATA_BASE}/swing.json`, signal);
    return getJson<SwingRow[]>(`${V1}/markets/swing`, signal);
  },
  catalysts(signal?: AbortSignal): Promise<CatalystsData> {
    return getJson<CatalystsData>(`${DATA_BASE}/catalysts.json`, signal);
  },
  extraIndices(signal?: AbortSignal): Promise<ExtraIndex[]> {
    return getJson<ExtraIndex[]>(`${DATA_BASE}/extra_indices.json`, signal).catch(() => []);
  },
  cot(signal?: AbortSignal): Promise<Record<string, CotData>> {
    return getJson<Record<string, CotData>>(`${DATA_BASE}/cot.json`, signal).catch(() => ({}));
  },
  movers(signal?: AbortSignal): Promise<MoversData> {
    return getJson<MoversData>(`${DATA_BASE}/movers.json`, signal).catch(() => ({
      generated_at: null,
      upgrades: [],
      downgrades: [],
    }));
  },
  meta(signal?: AbortSignal): Promise<SnapshotMeta> {
    if (IS_STATIC) return getJson<SnapshotMeta>(`${DATA_BASE}/meta.json`, signal);
    return getJson<SnapshotMeta>(`${V1}/markets/meta`, signal).catch(() => ({
      generated_at: null,
      securities: null,
      mode: "live",
    }));
  },
  async sectors(signal?: AbortSignal): Promise<string[]> {
    if (IS_STATIC) {
      const rows = await staticRows();
      return [...new Set(rows.map((r) => r.sector).filter((s): s is string => !!s))].sort();
    }
    return getJson<string[]>(`${V1}/screener/sectors`, signal);
  },
  health(signal?: AbortSignal): Promise<unknown> {
    if (IS_STATIC) return Promise.resolve({ status: "static" });
    return getJson(`${V1}/health`, signal);
  },
};
