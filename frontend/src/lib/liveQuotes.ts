// Live quotes, from whichever source is actually available.
//
//   1. VITE_API_BASE set   -> Server-Sent Events from the FastAPI backend (push, as before).
//   2. VITE_PRICE_PROXY set -> poll the Cloudflare Worker (the static site's only option).
//   3. neither             -> no-op.
//
// Path 2 is why the Worker exists. On the static site `BASE` is empty, so this module used to
// return a no-op and prices were only ever as fresh as the last batch refresh - and that batch
// is best-effort AND it now runs only every two hours: measured over eight days, GitHub started
// the then-half-hourly job 3-7 times a day instead of 48, and the cadence has since been cut to
// twelve a day to stop the snapshot commits growing the repository. That makes this path the
// only thing standing between the page and two-hour-old prices.
// The browser could fetch quotes itself except Yahoo sends no CORS header, so
// the Worker makes the call server-side and returns it with the header the browser needs.
//
// It asks only for the symbols ON SCREEN. That is the whole cost model: fifty rows a tick, not
// eleven thousand, which keeps a heavy session inside a few hundred of the free 100,000 daily
// requests.

export interface QuoteMsg {
  symbol: string; // provider_symbol
  price: number | null;
  change_pct: number | null;
}

const BASE = (import.meta.env.VITE_API_BASE ?? "").replace(/\/$/, "");

// The proxy URL is resolved at RUNTIME, not baked in at build time.
//
// It used to be compiled into the bundle from VITE_PRICE_PROXY, and that made a hosting
// detail into a build dependency: renaming a workers.dev subdomain - two clicks in the
// Cloudflare dashboard - silently killed live prices and required rebuilding and re-uploading
// 86 MB to restore them. The failure was invisible too, because the site falls back to
// snapshot prices and looks fine.
//
// Now `/config.json` wins if present, so the URL can be corrected by editing one small file.
// The build-time value stays as the fallback, so nothing that worked before stops working.
let PROXY = (import.meta.env.VITE_PRICE_PROXY ?? "").replace(/\/$/, "");

export interface RuntimeConfig {
  priceProxy?: string;
}

/** Load /config.json if it exists. Absent or malformed is FINE - it is an override, not a
 *  requirement, so a missing file must never stop the app booting. */
export async function loadRuntimeConfig(): Promise<void> {
  try {
    const resp = await fetch(`${import.meta.env.BASE_URL}config.json`, { cache: "no-store" });
    if (!resp.ok) return;
    const cfg = (await resp.json()) as RuntimeConfig;
    if (cfg.priceProxy) PROXY = String(cfg.priceProxy).replace(/\/$/, "");
  } catch {
    /* no config file, or not JSON - keep the build-time value */
  }
}

/** How often to re-poll. Fast enough to feel live, slow enough to stay far inside the quota. */
const POLL_MS = 20_000;
/** The Worker caps a request at 60 symbols; ask for no more than it will answer. */
const MAX_PER_POLL = 60;

export interface LiveOptions {
  symbols?: string[];
  /**
   * Called at each poll to ask what is currently visible. Preferred over `symbols` for the
   * screener, where the rows change as the user filters, sorts and scrolls - a fixed list
   * would keep pricing rows nobody is looking at.
   */
  getSymbols?: () => string[];
  onQuote: (q: QuoteMsg) => void;
  onOpen?: () => void;
  onError?: () => void;
}

function openSse(opts: LiveOptions): () => void {
  const params = opts.symbols?.length
    ? `?symbols=${encodeURIComponent(opts.symbols.join(","))}`
    : "";
  const es = new EventSource(`${BASE}/api/v1/stream/quotes${params}`);

  es.addEventListener("open", () => opts.onOpen?.());
  es.addEventListener("error", () => opts.onError?.());
  es.onmessage = (e) => {
    try {
      opts.onQuote(JSON.parse(e.data) as QuoteMsg);
    } catch {
      /* ignore malformed frames */
    }
  };
  return () => es.close();
}

function openPoll(opts: LiveOptions): () => void {
  let stopped = false;
  let timer: ReturnType<typeof setTimeout> | undefined;
  let announced = false;

  const tick = async () => {
    if (stopped) return;

    // Do not poll a tab nobody is looking at. Without this a dozen background tabs quietly
    // multiply the request count for prices no one can see.
    if (typeof document !== "undefined" && document.visibilityState === "hidden") {
      timer = setTimeout(tick, POLL_MS);
      return;
    }

    // PROXY is re-read every tick, not captured once. config.json loads asynchronously, so at
    // the moment this stream opens the URL may still be empty - checking once would leave live
    // prices permanently off for anyone whose config arrives a few milliseconds late.
    if (!PROXY) {
      timer = setTimeout(tick, POLL_MS);
      return;
    }

    const wanted = (opts.getSymbols?.() ?? opts.symbols ?? []).slice(0, MAX_PER_POLL);
    if (!wanted.length) {
      timer = setTimeout(tick, POLL_MS);
      return;
    }

    try {
      const url = `${PROXY}/quote?symbols=${encodeURIComponent(wanted.join(","))}`;
      const resp = await fetch(url);
      if (!resp.ok) throw new Error(String(resp.status));
      const body = (await resp.json()) as {
        quotes?: Record<string, { price?: number | null; changePct?: number | null }>;
      };
      if (stopped) return;

      if (!announced) {
        announced = true;
        opts.onOpen?.();
      }
      for (const [symbol, q] of Object.entries(body.quotes ?? {})) {
        opts.onQuote({
          symbol,
          price: q.price ?? null,
          change_pct: q.changePct ?? null,
        });
      }
    } catch {
      // A failed poll is not fatal - the snapshot price stays on screen. Drop the LIVE
      // indicator so the page stops claiming to be live when it is not, which is the whole
      // reason the indicator exists.
      announced = false;
      opts.onError?.();
    }

    if (!stopped) timer = setTimeout(tick, POLL_MS);
  };

  void tick();
  return () => {
    stopped = true;
    if (timer) clearTimeout(timer);
  };
}

export function openQuoteStream(opts: LiveOptions): () => void {
  if (BASE !== "") return openSse(opts);
  // Always poll when there is no backend. The poller itself waits for a proxy URL to appear,
  // so a config that loads after the first render still switches live prices on. Returning a
  // no-op here based on a value that had not arrived yet was a real bug: it would have looked
  // exactly like the proxy being down.
  return openPoll(opts);
}
