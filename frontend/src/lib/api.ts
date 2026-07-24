import type { Page, ScreenerQuery, ScreenerRow } from "@/types/api";
import type { CompanyDetail } from "@/types/company";

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
  health(signal?: AbortSignal): Promise<unknown> {
    if (IS_STATIC) return Promise.resolve({ status: "static" });
    return getJson(`${V1}/health`, signal);
  },
};
