"""Which companies just reported - so fundamentals refresh the day after, not on a timer.

A calendar-based refresh re-fetches companies that have nothing new and misses ones that
reported early. This drives the refresh off the announcements the platform already collects,
so a company that files today is picked up tomorrow.

The signals differ in quality by market, and pretending otherwise would be the bug:

  * PSX        - catalysts.json carries real per-company exchange announcements. Complete.
  * US         - the earnings calendar lists every company reporting on the day. Complete, but
                 it is scraped separately (it needs a browser) and passed in.
  * all others - the news feed is capped at ~40 items per region, so it catches the larger
                 names and nothing else.

Because India and Australia have no announcement source we can rely on, `pick` always mixes in
a small quota of the longest-stale companies. That is what guarantees every company is
eventually refreshed even where no signal exists - without it the gaps would be invisible.
"""

from __future__ import annotations

import json
import re
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from app.core.logging import get_logger
from app.ingestion.fundamentals_store import REGION_META, load, stale_symbols

log = get_logger(__name__)

# Deliberately broad: a missed announcement costs a day of staleness, while a false positive
# costs one page fetch. Mirrors the filter the PSX workflow already uses.
RESULT_RE = re.compile(
    r"result|financial|accounts|profit|earnings|\beps\b|board meeting|payout|"
    r"\bq[1-4]\b|quarter|half[- ]year|annual report",
    re.I,
)

# A company reporting on day D closes a period roughly 30-60 days earlier. If the store's
# newest period is already within this window of the announcement, we have the figures and the
# announcement is an echo - refetching would just re-download the same table daily.
COVERED_WITHIN_DAYS = 75


def _recent(text_date: str | None, since: date) -> bool:
    if not text_date:
        return False
    try:
        return date.fromisoformat(str(text_date)[:10]) >= since
    except ValueError:
        return False


def announced(data_dir: Path, days: int = 3) -> dict[str, str]:
    """{symbol: announcement date} from catalysts and the news feed."""
    since = datetime.now(UTC).date() - timedelta(days=days)
    out: dict[str, str] = {}

    try:
        cat = json.loads((data_dir / "catalysts.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        cat = {}
    for sym, events in (cat.get("by_symbol") or {}).items():
        for e in events or []:
            when = str(e.get("date") or "")[:10]
            if RESULT_RE.search(e.get("title") or "") and _recent(when, since):
                out[sym.upper()] = max(out.get(sym.upper(), ""), when)

    try:
        news = json.loads((data_dir / "news.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        news = {}
    for item in (news.get("items") or []):
        sym = (item.get("symbol") or "").upper()
        when = str(item.get("published_at") or "")[:10]
        if sym and RESULT_RE.search(item.get("title") or "") and _recent(when, since):
            out[sym] = max(out.get(sym, ""), when)

    return out


def _already_covered(rec: dict, announced_on: str) -> bool:
    """Do we already hold a period recent enough to be what was just announced?"""
    newest = next((p for p in (rec.get("periods") or []) if p), None)
    if not newest:
        return False
    try:
        end = date.fromisoformat(newest)
        when = date.fromisoformat(announced_on)
    except ValueError:
        return False
    return (when - end).days <= COVERED_WITHIN_DAYS


def pick(data_dir: Path, store_dir: Path, days: int = 3,
         backstop: int = 40, cap: int = 250) -> list[str]:
    """Symbols to re-scrape today: those that just reported, plus a staleness quota."""
    hits = announced(Path(data_dir), days)
    chosen: list[str] = []
    seen: set[str] = set()

    for region in REGION_META:
        data = load(region, Path(store_dir))
        companies = (data or {}).get("companies") or {}
        for sym, when in hits.items():
            if sym in seen or sym not in companies:
                continue
            if _already_covered(companies[sym], when):
                continue
            chosen.append(sym)
            seen.add(sym)

    reported = len(chosen)

    # Backstop. India and Australia have no announcement feed we can trust, so without this
    # they would drift indefinitely while the job reported success every day.
    for region in REGION_META:
        for sym in stale_symbols(region, Path(store_dir), older_than_days=100):
            if len(chosen) - reported >= backstop:
                break
            if sym not in seen:
                chosen.append(sym)
                seen.add(sym)

    log.info("results_watch.pick: %d reported + %d stale backstop (cap %d)",
             reported, len(chosen) - reported, cap)
    return chosen[:cap]
