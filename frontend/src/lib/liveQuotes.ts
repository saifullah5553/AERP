// Live quote stream client (Server-Sent Events).
// Reconnection is handled natively by EventSource; we expose open/error so the UI
// can show a "LIVE" indicator.

export interface QuoteMsg {
  symbol: string; // provider_symbol
  price: number | null;
  change_pct: number | null;
}

const BASE = (import.meta.env.VITE_API_BASE ?? "").replace(/\/$/, "");

export interface LiveOptions {
  symbols?: string[];
  onQuote: (q: QuoteMsg) => void;
  onOpen?: () => void;
  onError?: () => void;
}

export function openQuoteStream(opts: LiveOptions): () => void {
  const params = opts.symbols?.length ? `?symbols=${encodeURIComponent(opts.symbols.join(","))}` : "";
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
