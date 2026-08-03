"""Fill the missing `sector` for the expanded universe, keylessly.

Sector was present for under 10% of names, which made the Sector filter and the Sector
Rotation page useless for the expanded tail. Three free sources, no API keys:

* Yahoo's search endpoint - the primary. The only one that answers for EVERY market from one
  code path, and the only one that gives India a sector at all: NSE's free equity list has no
  sector column, so those names were previously left unset rather than guessed. It returns
  industry too, which neither of the others does.
* Australia - the ASX company directory CSV carries a GICS industry group.
* US - the SEC gives each filer's SIC code (data.sec.gov/submissions/CIK##########.json);
  we map the SIC major group onto the same GICS-style vocabulary the rest of the app uses,
  so the sector dropdown stays consistent instead of gaining hundreds of SIC descriptions.

The exchange-specific two are kept as fallbacks for names Yahoo does not know. Results are
cached (data/sector_cache*.json) because a sector changes about never and a re-run should cost
nothing.

Yahoo matches on the EXACT symbol: a search for a thin ticker readily returns a larger company,
and filing one company's sector under another is worse than leaving it blank.
"""

from __future__ import annotations

import csv
import io
import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx

from app.core.logging import get_logger
from app.core.safe_path import safe_file

log = get_logger(__name__)

_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko)"
_SEC_UA = "AERP equity research (contact via github.com/saifullah5553/AERP)"
_ASX_CSV = ("https://asx.api.markitdigital.com/asx-research/1.0/companies/directory/file"
            "?access_token=83ff96335c2d45a094df02a206a39ff4")
_CACHE = Path(__file__).resolve().parents[3] / "data" / "sector_cache.json"

# SIC major group (first 2 digits) -> GICS-style sector, matching the vocabulary already
# used by the curated names so the sector dropdown stays coherent.
_SIC2_SECTOR: dict[str, str] = {
    "01": "Consumer Staples", "02": "Consumer Staples", "07": "Consumer Staples",
    "08": "Materials", "09": "Consumer Staples",
    "10": "Materials", "12": "Energy", "13": "Energy", "14": "Materials",
    "15": "Industrials", "16": "Industrials", "17": "Industrials",
    "20": "Consumer Staples", "21": "Consumer Staples", "22": "Consumer Discretionary",
    "23": "Consumer Discretionary", "24": "Materials", "25": "Consumer Discretionary",
    "26": "Materials", "27": "Communication Services", "28": "Health Care",
    "29": "Energy", "30": "Materials", "31": "Consumer Discretionary",
    "32": "Materials", "33": "Materials", "34": "Industrials",
    "35": "Information Technology", "36": "Information Technology",
    "37": "Industrials", "38": "Health Care", "39": "Consumer Discretionary",
    "40": "Industrials", "41": "Industrials", "42": "Industrials", "43": "Industrials",
    "44": "Industrials", "45": "Industrials", "46": "Energy",
    "47": "Industrials", "48": "Communication Services", "49": "Utilities",
    "50": "Industrials", "51": "Industrials",
    "52": "Consumer Discretionary", "53": "Consumer Discretionary",
    "54": "Consumer Staples", "55": "Consumer Discretionary", "56": "Consumer Discretionary",
    "57": "Consumer Discretionary", "58": "Consumer Discretionary",
    "59": "Consumer Discretionary",
    "60": "Financials", "61": "Financials", "62": "Financials", "63": "Financials",
    "64": "Financials", "65": "Real Estate", "67": "Financials",
    "70": "Consumer Discretionary", "72": "Consumer Discretionary",
    "73": "Information Technology", "75": "Consumer Discretionary",
    "76": "Industrials", "78": "Communication Services", "79": "Consumer Discretionary",
    "80": "Health Care", "81": "Industrials", "82": "Consumer Discretionary",
    "83": "Health Care", "87": "Industrials", "89": "Industrials",
}
# A few SIC codes whose major group would mislead (chemicals vs pharma, software vs services).
_SIC4_SECTOR: dict[str, str] = {
    "2800": "Materials", "2810": "Materials", "2820": "Materials", "2821": "Materials",
    "2851": "Materials", "2860": "Materials", "2870": "Materials", "2890": "Materials",
    "2911": "Energy", "6798": "Real Estate", "6500": "Real Estate", "6512": "Real Estate",
    "6552": "Real Estate", "7372": "Information Technology", "7370": "Information Technology",
    "7371": "Information Technology", "7374": "Information Technology",
    "7812": "Communication Services", "4813": "Communication Services",
    "4832": "Communication Services", "4833": "Communication Services",
    "4841": "Communication Services", "4899": "Communication Services",
}


def sector_for_sic(sic: str | None) -> str | None:
    """GICS-style sector for a SIC code, or None when it can't be mapped."""
    if not sic:
        return None
    s = str(sic).strip().zfill(4)
    return _SIC4_SECTOR.get(s) or _SIC2_SECTOR.get(s[:2])


def _load_cache() -> dict[str, str]:
    try:
        return json.loads(_CACHE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _save_cache(cache: dict[str, str]) -> None:
    try:
        _CACHE.parent.mkdir(parents=True, exist_ok=True)
        _CACHE.write_text(json.dumps(cache), encoding="utf-8")
    except OSError:
        pass


def fetch_asx_sectors() -> dict[str, str]:
    """{'BHP.AX': 'Materials', ...} from the ASX directory CSV (one request)."""
    out: dict[str, str] = {}
    try:
        r = httpx.get(_ASX_CSV, headers={"User-Agent": _UA}, timeout=30, follow_redirects=True)
        r.raise_for_status()
        for row in csv.DictReader(io.StringIO(r.text)):
            code = (row.get("ASX code") or "").strip().upper()
            gics = (row.get("GICs industry group") or "").strip()
            # "Not Applic"/"--" are ASX placeholders, not sectors - leave those unset.
            if code and gics and gics not in {"--", "Not Applic", "Not Applicable", ""}:
                out[f"{code}.AX"] = gics
    except Exception as exc:  # noqa: BLE001 - optional enrichment
        log.warning("ASX sector fetch failed: %s", exc)
    return out


def fetch_us_sectors(tickers: set[str], throttle: float = 0.12) -> dict[str, str]:
    """{'AAPL': 'Information Technology', ...} via SEC SIC codes (keyless, throttled)."""
    from app.ingestion.us_universe import SECClient

    cache = _load_cache()
    out: dict[str, str] = {t: cache[t] for t in tickers if t in cache}
    todo = [t for t in tickers if t not in cache]
    if not todo:
        return out

    try:  # ticker -> CIK (one request for the whole market)
        cik_by_ticker = {
            e.ticker.strip().upper(): str(e.cik).zfill(10)
            for e in SECClient().fetch() if e.cik
        }
    except Exception as exc:  # noqa: BLE001
        log.warning("SEC universe fetch failed: %s", exc)
        return out

    headers = {"User-Agent": _SEC_UA}
    with httpx.Client(timeout=20, follow_redirects=True) as client:
        for i, t in enumerate(todo):
            cik = cik_by_ticker.get(t)
            if not cik:
                continue
            try:
                resp = client.get(
                    f"https://data.sec.gov/submissions/CIK{cik}.json", headers=headers
                )
                resp.raise_for_status()
                sector = sector_for_sic(resp.json().get("sic"))
            except Exception:  # noqa: BLE001 - one bad filer shouldn't stop the sweep
                sector = None
            if sector:
                out[t] = sector
                cache[t] = sector
            time.sleep(throttle)  # SEC asks for <=10 req/s; stay well under
            if i % 200 == 0:
                _save_cache(cache)
    _save_cache(cache)
    return out


# Instruments that are not companies. An ETF only lands here if no underlying sector was
# found - a sector-specific fund keeps the sector it actually tracks.
_ASSET_CLASS_SECTOR = {
    "forex": "Forex",
    "crypto": "Crypto",
    "index": "Index",
    "etf": "ETF",
    "commodity": "Commodity",
}

_YCACHE = Path(__file__).resolve().parents[3] / "data" / "sector_cache_yahoo.json"
_SEARCH = "https://query1.finance.yahoo.com/v1/finance/search"


def _load_ycache() -> dict[str, dict]:
    try:
        return json.loads(_YCACHE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def fetch_yahoo_sectors(provider_symbols: list[str], throttle: float = 0.05,
                        checkpoint: int = 400, workers: int = 8) -> dict[str, dict]:
    """{provider_symbol: {sector, industry}} from Yahoo's search endpoint.

    The only source that covers every market from one code path - India in particular, which
    the exchange feeds leave blank and this module previously left unset rather than guess.
    It also returns industry, which the SIC and GICS mappings do not.

    Keyless, and the same host we already take prices from. Cached, because sector changes
    about never and a re-run should cost nothing.
    """
    cache = _load_ycache()
    out: dict[str, dict] = {}
    todo = [s for s in provider_symbols if s not in cache]
    log.info("yahoo sectors: %d symbols, %d already cached", len(provider_symbols),
             len(provider_symbols) - len(todo))

    if todo:
        # One lookup per symbol over ~11k names is an hour serially. These are small, unrelated
        # GETs against a host we already poll, so they parallelise cleanly; the shared dict is
        # guarded because a torn cache write would silently lose a whole checkpoint.
        lock = threading.Lock()
        done = 0

        def fetch_one(sym: str, client: httpx.Client) -> None:
            nonlocal done
            try:
                r = client.get(_SEARCH, params={"q": sym, "quotesCount": 5, "newsCount": 0})
                quotes = (r.json() or {}).get("quotes") or []
                # Match the exact symbol: a search for a thin ticker readily returns a bigger
                # company, and filing one company's sector under another is worse than blank.
                hit = next((q for q in quotes if q.get("symbol") == sym), None)
                got = {"sector": (hit or {}).get("sector"),
                       "industry": (hit or {}).get("industry")}
            except Exception:  # noqa: BLE001 - one bad symbol must not stop the sweep
                got = {"sector": None, "industry": None}
            with lock:
                cache[sym] = got
                done += 1
                if done % checkpoint == 0:
                    _YCACHE.write_text(json.dumps(cache), encoding="utf-8")
                    log.info("yahoo sectors: %d/%d", done, len(todo))
            time.sleep(throttle)

        with httpx.Client(timeout=20, headers={"User-Agent": _UA}) as client:
            with ThreadPoolExecutor(max_workers=workers) as pool:
                list(pool.map(lambda s: fetch_one(s, client), todo))
        _YCACHE.write_text(json.dumps(cache), encoding="utf-8")

    for sym in provider_symbols:
        got = cache.get(sym) or {}
        if got.get("sector"):
            out[sym] = got
    return out


SECTOR_STORE = Path(__file__).resolve().parents[3] / "data" / "sectors"


def load_sector_store() -> dict[str, dict]:
    """{provider_symbol: {sector, industry, source}} from the versioned store."""
    out: dict[str, dict] = {}
    if not SECTOR_STORE.exists():
        return out
    for path in SECTOR_STORE.glob("*.csv"):
        try:
            with open(path, encoding="utf-8") as fh:
                for row in csv.DictReader(fh):
                    ps = (row.get("provider_symbol") or "").strip()
                    if ps and (row.get("sector") or "").strip():
                        out[ps] = {"sector": row["sector"].strip(),
                                   "industry": (row.get("industry") or "").strip() or None,
                                   "source": (row.get("source") or "").strip()}
        except OSError:
            continue
    return out


def save_sector_store(rows: list[dict]) -> dict[str, int]:
    """Write every resolved sector to data/sectors/<region>.csv.

    This is the point of the exercise: a sector changes about never, so re-deriving it from an
    external service on every run is a dependency we do not need. Once resolved it lives in the
    repo, and a lookup only happens for a symbol we have never seen.
    """
    SECTOR_STORE.mkdir(parents=True, exist_ok=True)
    by_region: dict[str, list[dict]] = {}
    for r in rows:
        if not r.get("sector") or not r.get("provider_symbol"):
            continue
        by_region.setdefault(str(r.get("region") or "unknown"), []).append(r)

    counts: dict[str, int] = {}
    for region, items in by_region.items():
        path = SECTOR_STORE / f"{region}.csv"
        with open(path, "w", encoding="utf-8", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(["provider_symbol", "symbol", "sector", "industry", "source"])
            for r in sorted(items, key=lambda x: str(x.get("provider_symbol"))):
                w.writerow([r["provider_symbol"], r.get("symbol", ""), r["sector"],
                            r.get("industry") or "", r.get("sector_source") or ""])
        counts[region] = len(items)
    log.info("sector store: %s", counts)
    return counts


def refresh_sectors(data_dir: str | Path, limit: int | None = None) -> dict[str, int]:
    """Patch missing `sector` on screener rows + company files (Australia + US)."""
    out = Path(data_dir)
    cdir = out / "company"
    rows: list[dict] = json.loads((out / "screener.json").read_text(encoding="utf-8"))

    # Our own store first - anything already resolved never needs looking up again.
    stored = load_sector_store()
    from_store = 0
    for r in rows:
        if r.get("sector") or not r.get("provider_symbol"):
            continue
        hit = stored.get(str(r["provider_symbol"]))
        if hit:
            r["sector"] = hit["sector"]
            if hit.get("industry") and not r.get("industry"):
                r["industry"] = hit["industry"]
            from_store += 1

    missing = [r for r in rows if not r.get("sector") and r.get("provider_symbol")]
    if limit is not None:
        missing = missing[:limit]

    # Yahoo first: it is the only source that answers for every market from one code path,
    # and it carries industry as well. The exchange-specific maps stay as a fallback for names
    # Yahoo does not know.
    yahoo = fetch_yahoo_sectors([str(r["provider_symbol"]) for r in missing])
    asx = fetch_asx_sectors()
    us_tickers = {
        str(r.get("symbol") or "").upper()
        for r in missing
        if r.get("region") == "us" and r.get("symbol")
        and str(r.get("provider_symbol")) not in yahoo
    }
    us = fetch_us_sectors(us_tickers) if us_tickers else {}

    filled = with_industry = 0
    for r in missing:
        ps = str(r.get("provider_symbol") or "")
        sym = str(r.get("symbol") or "").upper()
        hit = yahoo.get(ps) or {}
        sector = hit.get("sector") or (
            asx.get(ps) if r.get("region") == "australia" else us.get(sym)
        )
        if not sector:
            continue
        r["sector"] = sector
        industry = hit.get("industry")
        if industry and not r.get("industry"):
            r["industry"] = industry
            with_industry += 1
        # A ticker like CON resolves to a Windows device; opening it blocks forever.
        cf = safe_file(cdir, f"{ps}.json")
        if cf is not None and cf.exists():
            try:
                d = json.loads(cf.read_text(encoding="utf-8"))
                if isinstance(d.get("security"), dict):
                    d["security"]["sector"] = sector
                    if industry:
                        d["security"]["industry"] = industry
                    cf.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
            except (OSError, json.JSONDecodeError):
                pass
        filled += 1

    # Non-equities have no company sector to look up, but leaving them blank makes them
    # invisible to the sector filter and lumps them into an "unknown" bucket beside genuinely
    # missing equities. Labelling them by what they are keeps the filter honest and separates
    # "we could not find this" from "this does not have one".
    asset_filled = 0
    for r in rows:
        if r.get("sector"):
            continue
        label = _ASSET_CLASS_SECTOR.get(str(r.get("asset_class") or "").lower())
        if label:
            r["sector"] = label
            asset_filled += 1

    (out / "screener.json").write_text(json.dumps(rows), encoding="utf-8")
    save_sector_store(rows)
    result = {"missing": len(missing), "from_store": from_store, "yahoo_map": len(yahoo),
              "asx_map": len(asx), "us_map": len(us), "filled": filled,
              "industry_filled": with_industry, "by_asset_class": asset_filled}
    log.info("refresh-sectors: %s", result)
    return result
