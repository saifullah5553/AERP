// Reload when the tab comes back to a snapshot older than the one now published.
//
// Every page reads its data once, when it opens. A tab left open over a weekend kept Friday's
// numbers - market health, the up/down counts, every score - while "Updated 3d ago" quietly
// counted up beside them, and it looked as if the Daily had stopped. The site was current; the
// tab was not. Checking on return costs one 400-byte request.
import { api } from "@/lib/api";

const MIN_CHECK_GAP_MS = 60_000;
// Prices refresh through the day; a reload that throws away the reader's filters is worth it
// for a new day's snapshot, not for a quote half an hour newer.
const RELOAD_WHEN_BEHIND_MS = 60 * 60_000;

export function reloadWhenStale(): void {
  let loaded: string | null = null;
  let lastCheck = 0;

  const stamp = () => api.meta().then((m) => m?.generated_at ?? null).catch(() => null);
  void stamp().then((s) => {
    loaded = s;
  });

  const check = async () => {
    if (document.visibilityState !== "visible" || loaded === null) return;
    const now = Date.now();
    if (now - lastCheck < MIN_CHECK_GAP_MS) return;
    lastCheck = now;
    const current = await stamp();
    if (current && Date.parse(current) - Date.parse(loaded) > RELOAD_WHEN_BEHIND_MS) {
      window.location.reload();
    }
  };

  document.addEventListener("visibilitychange", () => void check());
}
