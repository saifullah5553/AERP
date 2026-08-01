"""Keyless per-company news refresh for the static snapshot (Google News RSS).

Patches the ``news`` array in each company/*.json directly — no DB, CI-friendly (Google News
RSS is reachable from datacenter IPs, unlike yfinance). Mirrors price_refresh/tech_refresh:
it only touches the news field, so it can never degrade scores or fundamentals.
"""

from __future__ import annotations

import hashlib
import json
import re
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from app.core.logging import get_logger
from app.ingestion.news import GoogleNewsClient

log = get_logger(__name__)

# Instruments where a per-name news search is meaningful. Forex/commodity/crypto/index
# "companies" don't have company news, so we skip them (avoids junk headlines).
_NEWS_REGIONS = {"psx", "us", "india", "gcc", "australia"}


def _query_for(name: str | None, symbol: str | None) -> str | None:
    if name:
        return f'"{name}"'
    if symbol:
        return f"{symbol} stock"
    return None


def _to_article(item: Any) -> dict[str, Any]:
    pub = getattr(item, "published_at", None)
    return {
        "published_at": pub.isoformat() if pub else None,
        "source": getattr(item, "source", None),
        "title": (item.title or "")[:512],
        "url": (item.url or "")[:1024],
        "summary": (getattr(item, "summary", None) or "")[:2000] or None,
        "sentiment": None,
        "dedupe_hash": hashlib.sha1(item.url.encode("utf-8")).hexdigest(),  # noqa: S324
    }


def _fetch(client: GoogleNewsClient, query: str, per: int) -> list[dict]:
    try:
        items = client.fetch(query)
    except Exception:  # noqa: BLE001 - one bad query shouldn't stop the batch
        return []
    # De-dupe by URL, keep the first `per`.
    seen: set[str] = set()
    out: list[dict] = []
    for it in items:
        if not it.url or it.url in seen:
            continue
        seen.add(it.url)
        out.append(_to_article(it))
        if len(out) >= per:
            break
    return out


def refresh_news(
    data_dir: str | Path,
    per: int = 8,
    workers: int = 6,
    limit: int | None = None,
    only_missing: bool = False,
) -> dict[str, int]:
    """Patch the `news` array in company/*.json for equity names via Google News RSS."""
    out = Path(data_dir)
    company_dir = out / "company"
    rows: list[dict] = json.loads((out / "screener.json").read_text(encoding="utf-8"))

    targets: list[tuple[str, str]] = []  # (provider_symbol, query)
    for r in rows:
        if r.get("region") not in _NEWS_REGIONS:
            continue
        ps = r.get("provider_symbol")
        if not ps or not (company_dir / f"{ps}.json").exists():
            continue
        if only_missing:
            try:
                d = json.loads((company_dir / f"{ps}.json").read_text(encoding="utf-8"))
                if d.get("news"):
                    continue
            except (OSError, json.JSONDecodeError):
                pass
        q = _query_for(r.get("name"), r.get("symbol"))
        if q:
            targets.append((ps, q))
    if limit is not None:
        targets = targets[:limit]

    client = GoogleNewsClient()
    results: dict[str, list[dict]] = {}
    with ThreadPoolExecutor(max_workers=workers) as pool:
        fetched = pool.map(lambda t: (t[0], _fetch(client, t[1], per)), targets)
        for ps, arts in fetched:
            if arts:
                results[ps] = arts

    patched = 0
    for ps, arts in results.items():
        cf = company_dir / f"{ps}.json"
        try:
            d = json.loads(cf.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        d["news"] = arts
        cf.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
        patched += 1

    n_index = _write_news_index(out, rows)
    result = {
        "targets": len(targets), "with_news": len(results),
        "patched": patched, "index": n_index,
    }
    log.info("refresh-news: %s", result)
    return result


# Auto-generated ticker/quote spam that Google News sometimes returns — not real news.
_JUNK_RE = re.compile(r"\|\s*Price:|Chg%|\|\s*Chg|Trading at |Stock Price, Quote")


def _write_news_index(out: Path, rows: list[dict], cap: int = 200) -> int:
    """Aggregate a cross-market recent-headlines feed (news.json) from all company files,
    balanced across markets (round-robin) so one market doesn't dominate the default view."""
    meta = {
        r.get("provider_symbol"): (r.get("symbol"), r.get("name"), r.get("region"))
        for r in rows
    }
    company_dir = out / "company"
    by_region: dict[str, list[dict]] = {}
    for ps, (sym, name, region) in meta.items():
        cf = company_dir / f"{ps}.json"
        if not cf.exists():
            continue
        try:
            arts = (json.loads(cf.read_text(encoding="utf-8")).get("news")) or []
        except (OSError, json.JSONDecodeError):
            continue
        for a in arts[:3]:  # a few per company so the feed isn't dominated by one name
            title = a.get("title") or ""
            if not title or _JUNK_RE.search(title):
                continue
            by_region.setdefault(region, []).append({
                "provider_symbol": ps, "symbol": sym, "name": name, "region": region,
                "title": title, "url": a.get("url"),
                "source": a.get("source"), "published_at": a.get("published_at"),
            })
    for lst in by_region.values():
        lst.sort(key=lambda x: x.get("published_at") or "", reverse=True)
    # Round-robin across markets so the default feed is balanced, not all one region.
    items: list[dict] = []
    i = 0
    while len(items) < cap and any(i < len(v) for v in by_region.values()):
        for lst in by_region.values():
            if i < len(lst):
                items.append(lst[i])
        i += 1
    items.sort(key=lambda x: x.get("published_at") or "", reverse=True)
    (out / "news.json").write_text(
        json.dumps({"items": items[:cap]}, ensure_ascii=False), encoding="utf-8"
    )
    return len(items[:cap])
