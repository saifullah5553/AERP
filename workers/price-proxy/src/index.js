/**
 * AERP live-price proxy — a Cloudflare Worker.
 *
 * WHY THIS EXISTS. Prices on the site are as fresh as the last batch refresh, and that batch
 * is best-effort: measured over eight days, GitHub delivered 3–7 scheduled runs a day instead
 * of 48. So a "30-minute" price is routinely hours old.
 *
 * The browser could fetch quotes itself and be genuinely live, except Yahoo sends no
 * Access-Control-Allow-Origin header, so the request dies in CORS before it starts. That is
 * the only reason prices are batched at all. A Worker sits in front, makes the request
 * server-side where CORS does not apply, and hands the result back with the header the
 * browser needs.
 *
 * The cost model is what makes this free and worth doing: the page asks only for the symbols
 * ON SCREEN — fifty rows, not eleven thousand — so a heavy session is a few hundred requests
 * against a free allowance of 100,000 a day.
 *
 * Endpoints:
 *   GET /quote?symbols=AAPL,MSFT,LUCK.KA     → { quotes: { SYM: {price, change, changePct, ts} } }
 *   GET /psx                                 → { quotes: {...} }  whole PSX market, one upstream call
 *   GET /health
 */

const YAHOO = "https://query1.finance.yahoo.com/v8/finance/chart/";
const PSX_MARKET_WATCH = "https://dps.psx.com.pk/market-watch";

// Seconds. Short enough to feel live, long enough that a hundred open tabs do not each become
// a hundred upstream calls — the edge cache collapses them into one.
const CACHE_SECONDS = 20;
const PSX_CACHE_SECONDS = 60;
const MAX_SYMBOLS = 60;

const CORS = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Methods": "GET, OPTIONS",
  "Access-Control-Max-Age": "86400",
};

function json(body, status = 200, extraHeaders = {}) {
  return new Response(JSON.stringify(body), {
    status,
    headers: {
      "content-type": "application/json; charset=utf-8",
      "cache-control": `public, max-age=${CACHE_SECONDS}`,
      ...CORS,
      ...extraHeaders,
    },
  });
}

/** One Yahoo chart call → the last close and the move against the previous bar. */
async function fetchQuote(symbol) {
  const url = `${YAHOO}${encodeURIComponent(symbol)}?range=5d&interval=1d`;
  const resp = await fetch(url, {
    headers: { "User-Agent": "Mozilla/5.0 (compatible; AERP/1.0)" },
    cf: { cacheTtl: CACHE_SECONDS, cacheEverything: true },
  });
  if (!resp.ok) return null;

  const data = await resp.json();
  const result = data?.chart?.result?.[0];
  if (!result) return null;

  const meta = result.meta || {};
  const closes = (result.indicators?.quote?.[0]?.close || []).filter((c) => c != null);
  // The BARS win over meta.regularMarketPrice. Yahoo freezes that field for some symbols while
  // still serving current bars underneath — 308 rows once carried a stale price for exactly
  // that reason, and the bar array was right the whole time.
  const price = closes.length ? closes[closes.length - 1] : meta.regularMarketPrice ?? null;
  const prev = closes.length > 1 ? closes[closes.length - 2] : meta.chartPreviousClose ?? null;
  if (price == null) return null;

  const change = prev == null ? null : price - prev;
  return {
    price,
    change,
    changePct: prev ? (change / prev) * 100 : null,
    currency: meta.currency ?? null,
    ts: meta.regularMarketTime ?? null,
  };
}

/** The whole PSX market in ONE upstream request — the exchange serves it as an HTML table. */
async function fetchPsx() {
  const resp = await fetch(PSX_MARKET_WATCH, {
    headers: {
      "User-Agent":
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36",
      Referer: "https://dps.psx.com.pk/",
    },
    cf: { cacheTtl: PSX_CACHE_SECONDS, cacheEverything: true },
  });
  if (!resp.ok) return {};

  const html = await resp.text();
  const quotes = {};
  // Deliberately a regex rather than an HTML parser: the Worker runtime has no DOM, the table
  // shape is stable, and pulling in a parser to read six numeric cells would be the heaviest
  // dependency in the project.
  const rowRe = /<tr[^>]*>([\s\S]*?)<\/tr>/g;
  const cellRe = /<td[^>]*>([\s\S]*?)<\/td>/g;
  let row;
  while ((row = rowRe.exec(html)) !== null) {
    const cells = [];
    let cell;
    while ((cell = cellRe.exec(row[1])) !== null) {
      cells.push(cell[1].replace(/<[^>]*>/g, "").replace(/&nbsp;/g, " ").trim());
    }
    if (cells.length < 8) continue;
    const symbol = cells[0];
    if (!symbol || !/^[A-Z0-9.\-]{2,20}$/.test(symbol)) continue;
    const num = (s) => {
      const v = parseFloat(String(s).replace(/,/g, ""));
      return Number.isFinite(v) ? v : null;
    };
    const price = num(cells[5]) ?? num(cells[4]);
    if (price == null || price <= 0) continue;
    const change = num(cells[6]);
    quotes[symbol] = {
      price,
      change,
      changePct: num(cells[7]),
      currency: "PKR",
      ts: null,
    };
  }
  return quotes;
}

export default {
  async fetch(request) {
    if (request.method === "OPTIONS") return new Response(null, { status: 204, headers: CORS });

    const url = new URL(request.url);

    if (url.pathname === "/health") {
      return json({ ok: true, service: "aerp-price-proxy" });
    }

    if (url.pathname === "/psx") {
      try {
        const quotes = await fetchPsx();
        return json({ quotes, count: Object.keys(quotes).length, source: "psx-market-watch" },
                    200, { "cache-control": `public, max-age=${PSX_CACHE_SECONDS}` });
      } catch (err) {
        return json({ error: String(err), quotes: {} }, 502);
      }
    }

    if (url.pathname === "/quote") {
      const raw = (url.searchParams.get("symbols") || "").trim();
      if (!raw) return json({ error: "symbols required", quotes: {} }, 400);

      // Capped on purpose. This endpoint exists to price what is ON SCREEN; anyone asking for
      // the whole universe wants the snapshot instead, and should not be able to turn one
      // request into eleven thousand upstream calls.
      const symbols = [...new Set(raw.split(",").map((s) => s.trim()).filter(Boolean))]
        .slice(0, MAX_SYMBOLS);

      const settled = await Promise.allSettled(symbols.map((s) => fetchQuote(s)));
      const quotes = {};
      let failed = 0;
      settled.forEach((r, i) => {
        if (r.status === "fulfilled" && r.value) quotes[symbols[i]] = r.value;
        else failed += 1;
      });
      // A partial answer beats an error: nineteen good prices and one gap is more useful than
      // a 502 that leaves the table showing nothing.
      return json({ quotes, requested: symbols.length, failed });
    }

    return json({ error: "not found", endpoints: ["/quote?symbols=", "/psx", "/health"] }, 404);
  },
};
