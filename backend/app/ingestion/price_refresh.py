"""Keyless price refresh for the static snapshot via Yahoo's chart v8 endpoint.

Unlike ``yfinance``'s quote/download endpoints (which 429 from datacenter/CI IPs), the
lightweight ``/v8/finance/chart/{symbol}`` endpoint IS reachable from GitHub runners and
returns the current (≈15-min delayed) quote for US/India/GCC/Australia/forex/etc.

This patches ONLY the price fields (price/change/change_pct/volume) in the already-exported
screener.json + company/*.json — it never touches scores, fundamentals, or regime, so a
price refresh can never degrade the rest of the snapshot. PSX is skipped (not on Yahoo; its
prices come from the PSX portal in the main pipeline).
"""

from __future__ import annotations

import json
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import httpx

from app.core.logging import get_logger
from app.core.safe_path import safe_file
from app.ingestion.ohlc_store import load_bars

log = get_logger(__name__)

# 5d, not 1d: one bar leaves nothing to fall back on when the quote block is frozen, and no
# previous close to compute a change from. Five sessions cover a long weekend and a holiday.
_CHART = "https://query1.finance.yahoo.com/v8/finance/chart/{sym}?range=5d&interval=1d"
_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko)"
_PSX_TZ = timezone(timedelta(hours=5))  # PKT, no DST


def _session_date(meta: dict[str, Any]) -> str | None:
    """The exchange-local trading date a quote belongs to.

    Without this a price has no age, so a row frozen in July looked exactly like one refreshed
    this minute - FCUV sat at its 31 July close, and nothing in the data said so. In the
    exchange's own timezone, not UTC: Sydney's session is already tomorrow by UTC reckoning,
    which would mark all of Australia a day stale every single day.
    """
    ts = meta.get("regularMarketTime")
    # 0 is not a date. PMGOLD.AX returns exactly that, and stamping it produced 1970-01-01 -
    # a bogus date is worse than no date, because it reads as a real answer.
    if not isinstance(ts, int | float) or ts <= 0:
        return None
    offset = meta.get("gmtoffset")
    if not isinstance(offset, int | float):
        offset = 0
    try:
        return datetime.fromtimestamp(ts + offset, tz=UTC).date().isoformat()
    except (OSError, OverflowError, ValueError):
        return None


def parse_chart_meta(meta: dict[str, Any]) -> dict[str, Any] | None:
    """Latest quote from a chart-v8 ``meta`` block, or None if there's no usable price."""
    price = meta.get("regularMarketPrice")
    if price is None:
        return None
    prev = meta.get("chartPreviousClose")
    if prev is None:
        prev = meta.get("previousClose")
    out: dict[str, Any] = {
        "price": price,
        "prev_close": prev,
        "day_open": meta.get("regularMarketOpen"),
        "day_high": meta.get("regularMarketDayHigh"),
        "day_low": meta.get("regularMarketDayLow"),
        "volume": meta.get("regularMarketVolume"),
        "as_of": _session_date(meta),
    }
    if prev not in (None, 0):
        out["change"] = round(price - prev, 6)
        out["change_pct"] = round((price - prev) / prev * 100.0, 6)
    else:
        out["change"] = None
        out["change_pct"] = None
    return out


def parse_chart_result(result: dict[str, Any]) -> dict[str, Any] | None:
    """A quote from a chart-v8 result, preferring the daily bars when the quote block is stale.

    Yahoo freezes the ``meta`` block for a few hundred listings while still serving current
    bars in the SAME response. It is not a rounding problem - the frozen quote is a different
    number entirely:

        SABAR.NS   meta 26.65 (24 Jul 2024)   last bar   6.55     4x too high
        AKIKO.NS   meta 76.75 (24 Jul 2024)   last bar 321.25     4x too low
        PMGOLD.AX  meta 17.94 (no timestamp)  last bar  60.50     3x too low

    308 rows carried prices like these, and every P/E, return and portfolio mark computed from
    them was wrong. So the bars win whenever they are newer than the quote, or whenever the
    quote has no date to judge it by.
    """
    meta = result.get("meta") or {}
    quote = parse_chart_meta(meta)

    stamps = result.get("timestamp") or []
    closes = ((result.get("indicators") or {}).get("quote") or [{}])[0].get("close") or []
    offset = meta.get("gmtoffset")
    if not isinstance(offset, int | float):
        offset = 0
    bars: list[tuple[str, float]] = []
    for stamp, close in zip(stamps, closes, strict=False):
        if not isinstance(stamp, int | float) or close is None:
            continue
        try:
            day = datetime.fromtimestamp(stamp + offset, tz=UTC).date().isoformat()
            value = float(close)
        except (OSError, OverflowError, TypeError, ValueError):
            continue
        if value > 0:
            bars.append((day, value))
    if not bars:
        return quote
    bars.sort()

    if quote and quote.get("as_of") and quote["as_of"] >= bars[-1][0]:
        # The quote is current, so keep it - but take the change from the bars. Over a 5-day
        # window ``chartPreviousClose`` is the close BEFORE the window, which turned Apple's
        # 0.29% day into 1.43% and would have re-sorted every gainers and losers table.
        prior = [c for day, c in bars if day < quote["as_of"]]
        if prior:
            prev, price = prior[-1], quote["price"]
            quote["prev_close"] = prev
            quote["change"] = round(price - prev, 6)
            quote["change_pct"] = round((price - prev) / prev * 100.0, 6)
        return quote

    day, price = bars[-1]
    prev = bars[-2][1] if len(bars) > 1 else None
    out: dict[str, Any] = {
        "price": price, "prev_close": prev, "as_of": day, "from_bars": True,
        "day_open": None, "day_high": None, "day_low": None, "volume": None,
        "change": None, "change_pct": None,
    }
    if prev:
        out["change"] = round(price - prev, 6)
        out["change_pct"] = round((price - prev) / prev * 100.0, 6)
    return out


def fetch_quote(sym: str, client: httpx.Client) -> dict[str, Any] | None:
    try:
        resp = client.get(_CHART.format(sym=sym), headers={"User-Agent": _UA}, timeout=15)
        resp.raise_for_status()
        result = resp.json()["chart"]["result"]
        if not result:
            return None
        return parse_chart_result(result[0])
    except Exception:  # noqa: BLE001 - one bad/delisted symbol shouldn't stop the batch
        return None


def _load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _eps_ttm(detail: dict) -> float | None:
    """Trailing-twelve-month EPS from OUR OWN quarterly-TTM statements.

    Reads `statements_ttm` - the scraped CSV series where every column is already a full
    trailing year - and takes the newest period that reports EPS. It used to read the annual
    `statements` block, which is where the yfinance backfill left its data, so the P/E on the
    page was a live price divided by an earnings figure from a banned source and a different
    basis. Same company, two vintages, one ratio.

    The newest TTM period often has no EPS yet (the source publishes the line a little after
    the rest of the statement), so the newest period that HAS one wins rather than giving up.
    """
    ttm = ((detail.get("statements_ttm") or {}).get("income")) or []
    if isinstance(ttm, list):
        for row in ttm:                      # newest first
            value = row.get("eps")
            if isinstance(value, int | float) and value != 0:
                return round(float(value), 4)
    return None


def _pe_ttm(price: Any, eps_ttm: float | None) -> float | None:
    """P/E (TTM). None for missing/zero/negative EPS (a loss has no meaningful P/E)."""
    if price is None or eps_ttm is None or eps_ttm <= 0:
        return None
    return round(float(price) / eps_ttm, 2)


def _add_psx_quotes(rows: list[dict], quotes: dict[str, dict]) -> None:
    """Populate `quotes` (keyed by provider_symbol) for PSX names from the official
    dps.psx.com.pk/market-watch table (live close/change/volume for the whole market)."""
    psx_map = {
        r.get("symbol"): r.get("provider_symbol")
        for r in rows
        if r.get("region") == "psx" and r.get("symbol") and r.get("provider_symbol")
    }
    if not psx_map:
        return
    try:
        from app.ingestion.psx_market import parse_market_watch, parse_symbols

        resp = httpx.get(
            "https://dps.psx.com.pk/market-watch", headers={"User-Agent": _UA}, timeout=25
        )
        resp.raise_for_status()
        marketrows = parse_market_watch(resp.text)
    except Exception as exc:  # noqa: BLE001 - network optional
        log.warning("PSX market-watch fetch failed: %s", exc)
        return

    # Sector per symbol from /symbols (title-cased), so PSX names get proper sectors.
    sectors: dict[str, str] = {}
    try:
        sresp = httpx.get(
            "https://dps.psx.com.pk/symbols", headers={"User-Agent": _UA}, timeout=25
        )
        sresp.raise_for_status()
        for s, meta in parse_symbols(sresp.text).items():
            if meta.sector:
                sectors[s] = meta.sector.title()
    except Exception as exc:  # noqa: BLE001 - network optional
        log.warning("PSX /symbols fetch failed: %s", exc)
    for mr in marketrows:
        ps = psx_map.get(mr.symbol)
        if not ps:
            continue
        price = mr.close if mr.close is not None else mr.ldcp
        if price is None:
            continue
        prev = mr.ldcp
        change = mr.change
        change_pct = mr.change_pct
        if change is None and prev not in (None, 0):
            change = round(price - prev, 4)
        if change_pct is None and prev not in (None, 0):
            change_pct = round((price - prev) / prev * 100.0, 4)
        quotes[ps] = {
            "price": price, "prev_close": prev, "change": change, "change_pct": change_pct,
            "day_open": mr.open, "day_high": mr.high, "day_low": mr.low, "volume": mr.volume,
            "sector": sectors.get(mr.symbol),
            # The market-watch table has no date column - it is whatever session the exchange is
            # showing right now, so date it in Karachi. Without a stamp all 453 PSX rows were
            # invisible to the staleness check, which is the one market we cannot re-fetch from
            # anywhere else.
            "as_of": datetime.now(tz=_PSX_TZ).date().isoformat(),
        }
    log.info("PSX market-watch: %d symbols patched", sum(1 for k in quotes if k.endswith(".KA")))


def refresh_prices(
    data_dir: str | Path,
    skip_regions: tuple[str, ...] = ("psx",),
    workers: int = 8,
    limit: int | None = None,
) -> dict[str, int]:
    """Patch price fields in screener.json + company/*.json for non-skipped regions."""
    out = Path(data_dir)
    screener_path = out / "screener.json"
    rows: list[dict] = _load(screener_path)

    targets = [
        r for r in rows
        if r.get("region") not in skip_regions and r.get("provider_symbol")
    ]
    if limit is not None:
        # STALEST FIRST, not the first N of a composite sort. The screener is composite-sorted,
        # so a fixed cap always refreshed the same head of the list and the tail was never
        # refreshed at all - not "later", never. FCUV kept its 31 July price for eight days
        # while its real price fell from 11.60 to 5.20. Ordering by age makes any cap a
        # rotation that self-heals: whatever misses this run is the stalest next run.
        targets.sort(key=lambda r: (r.get("price_as_of") or "", r.get("symbol") or ""))
        targets = targets[:limit]

    quotes: dict[str, dict] = {}
    syms = [r["provider_symbol"] for r in targets]
    client = httpx.Client(follow_redirects=True)
    try:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            for sym, q in zip(syms, pool.map(lambda s: fetch_quote(s, client), syms), strict=False):
                if q is not None:
                    quotes[sym] = q
    finally:
        client.close()

    # PSX prices from the official market-watch (Yahoo has no PSX). Patched directly here so
    # PSX stays robust even if the DB-based ingest hiccups. One fetch for the whole market.
    _add_psx_quotes(rows, quotes)

    updated = 0
    for r in rows:
        q = quotes.get(r.get("provider_symbol"))
        if not q:
            continue
        r["price"] = q["price"]
        r["change"] = q["change"]
        r["change_pct"] = q["change_pct"]
        if q.get("as_of"):
            r["price_as_of"] = q["as_of"]
        if q.get("volume") is not None:
            r["volume"] = q["volume"]
        if q.get("sector"):  # PSX sector from /symbols
            r["sector"] = q["sector"]
        # The DCF's upside is a gap between a fair value and a PRICE, so it goes stale the
        # moment the price moves. Recomputing it here - arithmetic on a value the quarterly
        # pass already worked out - is what keeps the two columns beside each other honest.
        # Without it the screener would show today's price against an upside computed off
        # last quarter's, and the pair would silently disagree.
        fair = r.get("dcf_fair_value")
        if isinstance(fair, int | float) and fair > 0 and q["price"]:
            r["dcf_upside_pct"] = round((fair / q["price"] - 1) * 100, 2)
            r["dcf_verdict"] = ("undervalued" if r["dcf_upside_pct"] > 20 else
                                "overvalued" if r["dcf_upside_pct"] < -20 else "fairly valued")
        # Keep return-since-signal in step with the fresh price (factual, not a forecast).
        pas = r.get("price_at_signal")
        if pas:
            r["signal_return_pct"] = round((q["price"] - pas) / pas * 100.0, 2)
        updated += 1

    # Patch each company file's quote block too (best-effort), and recompute P/E (TTM)
    # from the fresh price so valuation stays current every refresh. pe_by_sym then flows
    # back onto the screener rows below before screener.json is written.
    company_dir = out / "company"
    patched_files = 0
    failed_files = 0
    pe_by_sym: dict[str, float | None] = {}
    for sym, q in quotes.items():
        cf = safe_file(company_dir, f"{sym}.json")
        if cf is None:
            continue
        if not cf.exists():
            continue
        try:
            detail = _load(cf)
        except (json.JSONDecodeError, OSError):
            continue
        quote = dict(detail.get("quote") or {})
        quote.update({
            "price": q["price"], "prev_close": q["prev_close"],
            "change": q["change"], "change_pct": q["change_pct"],
        })
        # Only overwrite optional fields when this run actually has them (don't null out).
        for k in ("day_open", "day_high", "day_low", "volume"):
            if q.get(k) is not None:
                quote[k] = q[k]
        # P/E (TTM) from the fresh price ÷ trailing EPS (last-4-quarters, else latest annual).
        eps_ttm = _eps_ttm(detail)
        pe = _pe_ttm(q["price"], eps_ttm)
        pe_by_sym[sym] = pe
        quote["eps_ttm"] = eps_ttm
        quote["pe_ttm"] = pe
        detail["quote"] = quote
        if isinstance(detail.get("fundamentals"), dict):
            detail["fundamentals"]["pe_ttm"] = pe
        if isinstance(detail.get("ratios"), dict):
            detail["ratios"]["pe_ratio"] = pe
        if q.get("sector") and isinstance(detail.get("security"), dict):
            detail["security"]["sector"] = q["sector"]
        # Keep the company signal block's return-since in step with the fresh price too.
        sigblk = detail.get("signal")
        if isinstance(sigblk, dict) and sigblk.get("price_at_signal"):
            pas = sigblk["price_at_signal"]
            sigblk["signal_return_pct"] = round((q["price"] - pas) / pas * 100.0, 2)
        try:
            cf.write_text(json.dumps(detail, ensure_ascii=False), encoding="utf-8")
        except OSError as exc:
            # One locked file must not abort the other 11,464. This loop rewrites every company
            # file every half hour, so a scanner or an editor holding one open is routine -
            # and an unhandled OSError on CARE.json threw away the whole run's remaining work,
            # including the screener write that had not happened yet.
            failed_files += 1
            log.warning("price refresh: could not write %s (%s)", cf.name, exc)
            continue
        patched_files += 1

    # Apply the freshly-computed P/E (TTM) onto the screener rows, then persist.
    for r in rows:
        if r.get("provider_symbol") in pe_by_sym:
            r["pe_ttm"] = pe_by_sym[r["provider_symbol"]]
    screener_path.write_text(json.dumps(rows), encoding="utf-8")

    result = {"targets": len(targets), "quoted": len(quotes), "rows_updated": updated,
              "company_files": patched_files, "write_failures": failed_files,
              "pe_computed": sum(1 for v in pe_by_sym.values() if v)}
    result.update(report_staleness(rows))
    log.info("refresh-prices: %s", result)
    return result


def report_staleness(rows: list[dict]) -> dict[str, int]:
    """Count how many rows carry a price older than the freshest one in their own market.

    Logged every run so a coverage gap is a number somebody can see. A cap that silently
    excluded 6,069 symbols looked exactly like a full refresh from the outside; the only
    evidence was one company on one screen showing a price from eight days earlier.
    """
    # Grouped by asset class as well as market, because they keep different calendars. Crypto
    # trades on a Saturday and the FTSE does not, so measuring both against "the newest date in
    # global" reported all 51 indices, currencies and commodities as stale every weekend.
    def group(r: dict) -> tuple[str, str]:
        return (r.get("region") or "", r.get("asset_class") or "equity")

    newest: dict[tuple[str, str], str] = {}
    for r in rows:
        day = r.get("price_as_of")
        if day and r.get("region") and day > newest.get(group(r), ""):
            newest[group(r)] = day

    stale, undated = Counter(), 0
    for r in rows:
        key = group(r)
        if not key[0] or key not in newest:
            continue
        day = r.get("price_as_of")
        if not day:
            undated += 1
        elif day < newest[key]:
            stale[key[0]] += 1
    if stale or undated:
        log.warning("price staleness: %d rows behind their market (%s), %d with no price date",
                    sum(stale.values()), dict(stale), undated)
    return {"stale_rows": sum(stale.values()), "undated_rows": undated}


def fill_missing_prices(out: Path) -> dict[str, int]:
    """Give a row a price from our OWN daily history when the live feed had none.

    PSX quotes come from the exchange portal and 70 names arrive without one. An unpriced row
    is invisible to every portfolio - it cannot be bought, so it is filtered out of the ranking
    - which is how UBL sat at rank 21 by quality and appeared in nothing. 60 SCORED companies
    were being excluded for want of a number we already hold.

    Deliberately NOT Yahoo's live quote. For UBL.KA that field reads 259.59 while Yahoo's own
    closes for the same days run 462-478 and no split is reported; the quote is simply wrong
    for these listings. The last stored close is consistent with the history every return is
    computed from, which matters more here than being an hour fresher.
    """
    path = out / "screener.json"
    try:
        rows = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"filled": 0, "moves": 0}

    filled = moved = 0
    for r in rows:
        # The DAILY MOVE, from the same stored history, whenever the live feed did not supply
        # one. This is what the advancers/decliners tiles count, and they were counting only
        # the rows that happened to have it: Saudi showed 11 up and 11 down out of 385 because
        # 23 rows carried a change, and Dubai showed 0 and 0 because none did. A market tile
        # reporting on 6% of its market reads as the market.
        if r.get("change_pct") is None:
            region, symbol = str(r.get("region") or ""), str(r.get("symbol") or "")
            if region and symbol:
                try:
                    bars = load_bars(region, symbol)
                except Exception:  # noqa: BLE001
                    bars = {}
                days = sorted(bars)[-2:] if bars else []
                if len(days) == 2:
                    try:
                        prev, last = float(bars[days[0]][4]), float(bars[days[1]][4])
                    except (TypeError, ValueError, IndexError):
                        prev = last = 0.0
                    if prev > 0 and last > 0:
                        r["change"] = round(last - prev, 6)
                        r["change_pct"] = round((last / prev - 1) * 100, 6)
                        moved += 1

        if r.get("price") is not None:
            continue
        region, symbol = str(r.get("region") or ""), str(r.get("symbol") or "")
        if not region or not symbol:
            continue
        try:
            bars = load_bars(region, symbol)
        except Exception:  # noqa: BLE001 - a missing history is not an error here
            continue
        if not bars:
            continue
        last = max(bars)
        try:
            close = float(bars[last][4])
        except (TypeError, ValueError, IndexError):
            continue
        if close <= 0:
            continue
        r["price"] = close
        # Said out loud, so a stale close is never mistaken for a live quote.
        r["price_source"] = f"last close {last}"
        filled += 1

    if filled or moved:
        path.write_text(json.dumps(rows), encoding="utf-8")
        log.info("fill-missing-prices: %d rows priced from stored history", filled)
    return {"filled": filled}
