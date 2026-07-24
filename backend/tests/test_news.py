from __future__ import annotations

import httpx
from app.ingestion.news import GoogleNewsClient, ingest_news_for_security, parse_rss
from app.models.enums import AssetClass, MarketRegion
from app.models.market import Market, Security
from app.models.market_intel import NewsArticle
from sqlalchemy import func, select
from sqlalchemy.orm import Session

RSS = """<?xml version="1.0"?>
<rss version="2.0"><channel>
  <item>
    <title>Apple hits record high</title>
    <link>https://news.google.com/articles/x1</link>
    <pubDate>Wed, 22 Jul 2026 10:00:00 GMT</pubDate>
    <source url="https://reuters.com">Reuters</source>
    <description>Apple stock rallied.</description>
  </item>
  <item>
    <title>Apple earnings beat estimates</title>
    <link>https://news.google.com/articles/x2</link>
    <pubDate>Tue, 21 Jul 2026 09:00:00 GMT</pubDate>
    <source url="https://bloomberg.com">Bloomberg</source>
  </item>
</channel></rss>"""


def _mock_client() -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "news.google.com":
            return httpx.Response(200, text=RSS)
        return httpx.Response(404)

    return httpx.Client(transport=httpx.MockTransport(handler))


def test_parse_rss() -> None:
    items = parse_rss(RSS)
    assert len(items) == 2
    assert items[0].title == "Apple hits record high"
    assert items[0].source == "Reuters"
    assert items[0].published_at is not None and items[0].published_at.year == 2026
    assert items[0].url.endswith("x1")


def _security(db: Session) -> Security:
    market = Market(code="NASDAQ", name="NASDAQ", region=MarketRegion.US,
                    currency="USD", ticker_suffix="")
    db.add(market)
    db.flush()
    sec = Security(market_id=market.id, symbol="AAPL", provider_symbol="AAPL",
                   name="Apple Inc.", asset_class=AssetClass.EQUITY, currency="USD")
    db.add(sec)
    db.commit()
    return sec


def test_ingest_and_dedupe(db: Session) -> None:
    sec = _security(db)
    client = GoogleNewsClient(_mock_client())

    written = ingest_news_for_security(db, client, sec)
    db.commit()
    assert written == 2
    assert db.scalar(select(func.count()).select_from(NewsArticle)) == 2

    again = ingest_news_for_security(db, client, sec)  # same URLs → deduped
    db.commit()
    assert again == 0
    assert db.scalar(select(func.count()).select_from(NewsArticle)) == 2
