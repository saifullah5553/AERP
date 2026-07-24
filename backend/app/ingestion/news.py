"""News ingestion from Google News RSS (free, keyless).

For each active security we query Google News for the company and store recent
headlines in ``news_articles`` (deduped by URL). Google News RSS needs no key and
covers global outlets, so it works for US, PSX, India, and GCC names alike. HTTP is
injectable and the RSS parser is pure, so the logic is testable without a network.
"""

from __future__ import annotations

import hashlib
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.models.market import Security
from app.models.market_intel import NewsArticle

log = get_logger(__name__)

BASE_URL = "https://news.google.com/rss/search"
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; AERP/1.0)"}
DEFAULT_TIMEOUT = httpx.Timeout(20.0, connect=8.0)


@dataclass(slots=True)
class NewsItem:
    title: str
    url: str
    published_at: datetime | None
    source: str | None
    summary: str | None


def _dedupe_hash(url: str) -> str:
    return hashlib.sha1(url.encode("utf-8")).hexdigest()  # noqa: S324 (not security-sensitive)


def parse_rss(xml_text: str) -> list[NewsItem]:
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return []
    items: list[NewsItem] = []
    for it in root.findall(".//item"):
        title = (it.findtext("title") or "").strip()
        link = (it.findtext("link") or "").strip()
        if not title or not link:
            continue
        pub_raw = it.findtext("pubDate")
        published: datetime | None = None
        if pub_raw:
            try:
                published = parsedate_to_datetime(pub_raw)
            except (TypeError, ValueError):
                published = None
        src_el = it.find("source")
        source = src_el.text.strip() if src_el is not None and src_el.text else None
        summary = (it.findtext("description") or "").strip() or None
        items.append(NewsItem(title, link, published, source, summary))
    return items


class GoogleNewsClient:
    def __init__(self, client: httpx.Client | None = None) -> None:
        self._client = client

    def _http(self) -> httpx.Client:
        if self._client is None:
            self._client = httpx.Client(timeout=DEFAULT_TIMEOUT, follow_redirects=True)
        return self._client

    def fetch(self, query: str) -> list[NewsItem]:
        params = {"q": query, "hl": "en-US", "gl": "US", "ceid": "US:en"}
        try:
            resp = self._http().get(BASE_URL, params=params, headers=HEADERS)
            resp.raise_for_status()
            return parse_rss(resp.text)
        except Exception as exc:
            log.warning("Google News fetch failed for %r: %s", query, exc)
            return []


def _query_for(security: Security) -> str:
    if security.name:
        return f'"{security.name}"'
    return f"{security.symbol} stock"


def ingest_news_for_security(
    db: Session, client: GoogleNewsClient, security: Security, per_symbol: int = 10
) -> int:
    items = client.fetch(_query_for(security))[:per_symbol]
    written = 0
    for item in items:
        digest = _dedupe_hash(item.url)
        if db.scalar(select(NewsArticle.id).where(NewsArticle.dedupe_hash == digest)):
            continue
        db.add(
            NewsArticle(
                security_id=security.id,
                published_at=item.published_at or datetime.now(UTC),
                source=item.source,
                title=item.title[:512],
                url=item.url[:1024],
                summary=item.summary,
                dedupe_hash=digest,
            )
        )
        written += 1
    return written


def ingest_news(
    db: Session, client: GoogleNewsClient, limit: int | None = None, per_symbol: int = 10
) -> dict[str, int]:
    stmt = select(Security).where(Security.is_active.is_(True))
    if limit is not None:
        stmt = stmt.limit(limit)
    securities = list(db.scalars(stmt))
    total = 0
    covered = 0
    for security in securities:
        n = ingest_news_for_security(db, client, security, per_symbol)
        if n:
            covered += 1
            total += n
            db.commit()
    result = {"securities": len(securities), "covered": covered, "articles": total}
    log.info("ingest_news: %s", result)
    return result
