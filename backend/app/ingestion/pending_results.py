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
import time
from datetime import UTC, datetime, timedelta
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
    if r.status_code != 200:
        return None
    m = _DATEKEY.search(r.text)
    return m.group(1) if m else None


def held_periods(region: str, store_dir: Path) -> dict[str, str]:
    """{symbol: newest period we already hold}."""
    store = load_store(region, store_dir)
    out: dict[str, str] = {}
    for symbol, rec in ((store or {}).get("companies") or {}).items():
        periods = [p for p in (rec.get("periods") or []) if p]
        if periods:
            out[str(symbol).upper()] = max(periods)
    return out


def probe_for_new_quarters(region: str, symbols: list[str], store_dir: Path,
                           pause: float = 0.55) -> tuple[set[str], dict[str, str]]:
    """Symbols whose newest period AT THE SOURCE is ahead of what we hold.

    This is the definitive test, and the reason it exists: an announcement can be missed, worded
    unusually, or fall out of a rolling feed. A period we do not have cannot be any of those.
    """
    held = held_periods(region, store_dir)
    pending: set[str] = set()
    seen: dict[str, str] = {}
    with httpx.Client(headers={"User-Agent": _UA}, timeout=25,
                      follow_redirects=True) as client:
        for i, symbol in enumerate(symbols, 1):
            newest = newest_at_source(region, symbol, client)
            if newest:
                seen[symbol] = newest
                if newest > held.get(symbol.upper(), ""):
                    pending.add(symbol.upper())
            if i % 100 == 0:
                log.info("pending[%s]: probed %d/%d", region, i, len(symbols))
            time.sleep(pause)
    log.info("pending[%s]: %d of %d have a quarter we do not hold",
             region, len(pending), len(symbols))
    return pending, seen


def write_pending(region: str, symbols: set[str], note: str = "") -> Path:
    """Write the list the scraper reads. One symbol per line, # comments ignored."""
    PENDING_DIR.mkdir(parents=True, exist_ok=True)
    path = PENDING_DIR / f"{region}.txt"
    header = [
        f"# {region.upper()} - companies with results we do not hold yet.",
        f"# Written {datetime.now(UTC).date().isoformat()}. Consumed by the fundamentals",
        "# workflow, which scrapes ONLY these. Delete the file to force a full sweep.",
    ]
    if note:
        header.append(f"# {note}")
    path.write_text("\n".join(header + sorted(symbols)) + "\n", encoding="utf-8")
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
                  f"probe found a newer quarter for: {len(pending - announced)}")
    return {"announced": len(announced & universe), "pending": len(pending),
            "probed": len(probed)}
