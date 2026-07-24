import type { Page, ScreenerQuery, ScreenerRow } from "@/types/api";

const BASE = (import.meta.env.VITE_API_BASE ?? "").replace(/\/$/, "");
const V1 = `${BASE}/api/v1`;

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
  if (!res.ok) {
    throw new Error(`API ${res.status} ${res.statusText} for ${url}`);
  }
  return (await res.json()) as T;
}

export const api = {
  screener(query: ScreenerQuery, signal?: AbortSignal): Promise<Page<ScreenerRow>> {
    return getJson<Page<ScreenerRow>>(`${V1}/screener${qs({ ...query })}`, signal);
  },
  health(signal?: AbortSignal): Promise<unknown> {
    return getJson(`${V1}/health`, signal);
  },
};
