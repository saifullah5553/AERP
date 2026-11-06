"""Which companies have results we do not hold yet - written to a file, one symbol per line.

Two signals, and the second is the one that matters.

ANNOUNCEMENTS. catalysts.json carries per-company exchange filings. Cheap and immediate, but a
ROLLING window: on 5 August it held nothing before 3 August, so anything filed in July had
already aged out. Asked for PSX companies that had reported, it offered 17. Fifty had.

THE SOURCE ITSELF. Every stockanalysis financials page states its newest reported period in the
payload, and a plain GET can read it - no browser needed. Comparing that with the newest period
in our store answers the real question: does this company have a quarter we do not hold? It
found all fifty, including HBL, UBL and NESTLE, which the feed never mentioned.

So the file is the union, and the probe is what makes it complete. The announcement feed stays
because it is free and instant; the probe costs one light request per company and is the only
thing that cannot silently miss a filer.

    data/pending/psx.txt
"""

from __future__ import annotations

import json
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import httpx

from app.core.logging import get_logger
from app.ingestion.fundamentals_store import load as load_store
from app.ingestion.results_watch import RESULT_RE

log = get_logger(__name__)

PENDING_DIR = Path(__file__).resolve().parents[3] / "data" / "pending"
SA_PREFIX = {
    "psx": "quote/psx", "us": "stocks", "india": "quote/nse",
    "australia": "quote/asx", "gcc": "quote/tadawul", "dfm": "quote/dfm",
}
_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")
# A company we could not ask about, but whose newest period is at least this old, is treated as
# pending: a full quarter plus a filing window has passed, so a fetch is justified without the
# probe's answer. Below this it stays out, because it may simply have nothing new.
ASSUME_DUE_AFTER_DAYS = 120
# Per-market ceiling on probing, so a throttled source cannot eat the whole job's time limit.
MAX_PROBE_SECONDS = 1500
COOLDOWN_SECONDS = 30.0
MAX_COOLDOWN_SECONDS = 120.0
PROBE_ATTEMPTS = 4
# The newest reported period, as the page states it in its own payload.
_DATEKEY = re.compile(r'datekey:\["(\d{4}-\d{2}-\d{2})"')


def announced_recently(data_dir: Path, region: str, days: int = 5) -> set[str]:
    """Symbols with a results-shaped announcement in the last `days`. Cheap, incomplete."""
    since = (datetime.now(UTC).date() - timedelta(days=days)).isoformat()
    try:
        cat = json.loads((data_dir / "catalysts.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return set()
    out: set[str] = set()
    for symbol, events in (cat.get("by_symbol") or {}).items():
        for ev in events or []:
            when = str(ev.get("date") or "")[:10]
            if when >= since and RESULT_RE.search(str(ev.get("title") or "")):
                out.add(str(symbol).upper())
                break
    log.info("pending[%s]: %d symbols announced in the last %d days", region, len(out), days)
    return out


class Throttled(Exception):
    """The source refused to answer. That is NOT the same as "nothing new"."""


def newest_at_source(region: str, symbol: str, client: httpx.Client) -> str | None:
    """The newest period the source reports for this company, or None if it has no page."""
    prefix = SA_PREFIX.get(region)
    if not prefix:
        return None
    try:
        r = client.get(f"https://stockanalysis.com/{prefix}/{symbol}"
                       f"/financials/income-statement/?p=trailing")
    except httpx.HTTPError:
        return None
    if r.status_code in (403, 429):
        raise Throttled(str(r.status_code))
    if r.status_code != 200:
        return None
    m = _DATEKEY.search(r.text)
    return m.group(1) if m else None


def company_sizes(rows: list[dict], region: str, store_dir: Path) -> dict[str, float]:
    """{symbol: size}, for deciding who is scraped first: the market cap, or price x shares.

    The published cap comes from the DCF, which stops early for banks. JPMorgan, Wells Fargo and
    Goldman had none, ranked as zero, and queued alphabetically behind 1,800 smaller companies.
    This is for ordering only. The score reads the published cap, so it is not filled in here.
    """
    store = (load_store(region, store_dir) or {}).get("companies") or {}
    sizes: dict[str, float] = {}
    for row in rows:
        symbol = row.get("symbol")
        if row.get("region") != region or not symbol:
            continue
        symbol = str(symbol)
        shares = (store.get(symbol.upper(), {}).get("income") or {}).get("weighted_shares") or []
        latest = next((count for count in shares if count), 0)
        sizes[symbol] = row.get("market_cap") or (row.get("price") or 0) * latest
    return sizes


def _newest_complete(rec: dict) -> str | None:
    """The newest period with a balance sheet behind it, or the newest at all if none has.

    The source publishes headline figures first: LUCK's Sep-26 column has revenue and profit and
    no equity, debt or EPS. Such a column cannot be scored, and counting it as held meant it was
    never asked for again, so the company stayed on a thin quarter after the source had filled it.
    """
    periods = rec.get("periods") or []
    equity = (rec.get("balance") or {}).get("total_equity") or []
    complete = [p for p, value in zip(periods, equity, strict=False) if p and value is not None]
    return max(complete) if complete else max((p for p in periods if p), default=None)


def held_periods(region: str, store_dir: Path) -> dict[str, str]:
    """{symbol: newest complete period we already hold}."""
    store = load_store(region, store_dir)
    out: dict[str, str] = {}
    for symbol, rec in ((store or {}).get("companies") or {}).items():
        newest = _newest_complete(rec)
        if newest:
            out[str(symbol).upper()] = newest
    return out


# A quarter cannot appear before roughly a quarter has passed, plus the weeks companies take
# to report. Below this, asking is guaranteed to tell us what we already know.
MIN_AGE_DAYS = 100


def due_for_probe(held: str | None, today: date, min_age_days: int = MIN_AGE_DAYS) -> bool:
    """Could this company plausibly have filed something we do not have?

    Across five markets the universe is 11,684 names, which serially is over an hour and most
    of it wasted: a company whose newest period is six weeks old cannot have a newer one. Only
    the ones old enough to have reported again are asked.
    """
    if not held:
        return True
    try:
        end = date.fromisoformat(str(held)[:10])
    except ValueError:
        return True
    return (today - end).days >= min_age_days


def assume_due(held: str | None, today: date) -> bool:
    """Stale enough to fetch even though the source would not confirm a newer period."""
    if not held:
        return True
    try:
        return (today - date.fromisoformat(str(held)[:10])).days >= ASSUME_DUE_AFTER_DAYS
    except ValueError:
        return True


def probe_for_new_quarters(region: str, symbols: list[str], store_dir: Path,
                           pause: float = 0.25, workers: int = 6
                           ) -> tuple[set[str], dict[str, str]]:
    """Symbols whose newest period AT THE SOURCE is ahead of what we hold.

    This is the definitive test, and the reason it exists: an announcement can be missed, worded
    unusually, or fall out of a rolling feed. A period we do not have cannot be any of those.

    A throttled answer is not an answer. This used to read a 429 as "no newer period", so when
    the source rate-limited the probe the list silently shrank: on 5 Nov 2026 it reported 94 US
    companies pending while Apple, Microsoft, JPMorgan and every other name that answered had a
    quarter we did not hold. All workers now wait out a shared cooldown, and whatever could not
    be checked is counted, reported, and treated as due if it is old enough.
    """
    held = held_periods(region, store_dir)
    today = datetime.now(UTC).date()
    due = [s for s in symbols if due_for_probe(held.get(s.upper()), today)]
    log.info("pending[%s]: %d of %d are old enough to have reported again",
             region, len(due), len(symbols))

    pending: set[str] = set()
    seen: dict[str, str] = {}
    unknown: set[str] = set()
    lock = threading.Lock()
    deadline = time.time() + MAX_PROBE_SECONDS
    gate = {"resume": 0.0, "cooldown": COOLDOWN_SECONDS}

    def one(symbol: str, client: httpx.Client) -> None:
        newest = None
        for _ in range(PROBE_ATTEMPTS):
            wait = gate["resume"] - time.time()
            if wait > 0:
                time.sleep(wait)
            if time.time() >= deadline:
                break
            try:
                newest = newest_at_source(region, symbol, client)
            except Throttled:
                with lock:
                    if time.time() >= gate["resume"]:
                        gate["resume"] = time.time() + gate["cooldown"]
                        gate["cooldown"] = min(gate["cooldown"] * 2, MAX_COOLDOWN_SECONDS)
                continue
            gate["cooldown"] = COOLDOWN_SECONDS
            time.sleep(pause)
            if not newest:
                return
            break
        else:
            newest = None
        if not newest:
            with lock:
                unknown.add(symbol)
            return
        with lock:
            seen[symbol] = newest
            if newest > held.get(symbol.upper(), ""):
                pending.add(symbol.upper())

    with (
        httpx.Client(headers={"User-Agent": _UA}, timeout=25, follow_redirects=True) as client,
        ThreadPoolExecutor(max_workers=workers) as pool,
    ):
        list(pool.map(lambda s: one(s, client), due))

    log.info("pending[%s]: %d of %d probed have a quarter we do not hold",
             region, len(pending), len(due))
    if unknown:
        stale = {s.upper() for s in unknown if assume_due(held.get(s.upper()), today)}
        pending |= stale
        # A warning annotation, because job logs need a token to read and this must be visible.
        print(f"::warning::pending[{region}]: source would not answer for {len(unknown)} of "
              f"{len(due)}; {len(stale)} are old enough to fetch anyway", flush=True)
        log.warning("pending[%s]: could not check %d of %d; %d assumed due",
                    region, len(unknown), len(due), len(stale))
    return pending, seen


def write_pending(region: str, symbols: set[str], note: str = "",
                  order: list[str] | None = None) -> Path:
    """Write the list the scraper reads. One symbol per line, # comments ignored.

    In `order` where given, then alphabetically. A list longer than a day's scrape budget is
    worked from the top, so its order decides who waits.
    """
    PENDING_DIR.mkdir(parents=True, exist_ok=True)
    path = PENDING_DIR / f"{region}.txt"
    header = [
        f"# {region.upper()} - companies with results we do not hold yet.",
        f"# Written {datetime.now(UTC).date().isoformat()}. Consumed by the fundamentals",
        "# workflow, which scrapes ONLY these. Delete the file to force a full sweep.",
    ]
    if note:
        header.append(f"# {note}")
    rank = {s: i for i, s in enumerate(order or [])}
    ranked = sorted(symbols, key=lambda s: (rank.get(s, len(rank)), s))
    path.write_text("\n".join(header + ranked) + "\n", encoding="utf-8")
    log.info("pending[%s]: wrote %d symbols -> %s", region, len(symbols), path)
    return path


def read_pending(region: str) -> list[str]:
    path = PENDING_DIR / f"{region}.txt"
    if not path.exists():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        sym = line.split("#", 1)[0].strip().upper()
        if sym:
            out.append(sym)
    return out


def build(data_dir: Path, store_dir: Path, region: str, symbols: list[str],
          days: int = 5, probe: bool = True) -> dict[str, int]:
    """Announcements ∪ source-probe, written to data/pending/<region>.txt."""
    announced = announced_recently(data_dir, region, days)
    # Keep only names we actually carry - an announcement for something not in the universe
    # would send the scraper after a page that does not concern us.
    universe = {s.upper() for s in symbols}
    pending = {s for s in announced if s in universe}

    probed: dict[str, str] = {}
    if probe:
        found, probed = probe_for_new_quarters(region, symbols, store_dir)
        pending |= found

    write_pending(region, pending,
                  f"announced in {days}d: {len(announced & universe)}; "
                  f"probe found a newer quarter for: {len(pending - announced)}",
                  order=[s.upper() for s in symbols])
    return {"announced": len(announced & universe), "pending": len(pending),
            "probed": len(probed)}
