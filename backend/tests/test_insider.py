from __future__ import annotations

import json
from datetime import date

import httpx
from app.engines.insider.engine import analyze, compute_for_security
from app.ingestion.insider import EdgarClient, ingest_insider_for_security, parse_form4
from app.models.corporate import InsiderSummary, InsiderTransaction
from app.models.enums import AssetClass, InsiderTransactionType, MarketRegion
from app.models.market import Market, Security
from sqlalchemy.orm import Session

# A minimal Form 4: one open-market purchase (code P), one grant (code A, ignored).
FORM4_XML = """<?xml version="1.0"?>
<ownershipDocument>
  <reportingOwner>
    <reportingOwnerId><rptOwnerName>Jane Insider</rptOwnerName></reportingOwnerId>
    <reportingOwnerRelationship><officerTitle>CEO</officerTitle></reportingOwnerRelationship>
  </reportingOwner>
  <nonDerivativeTable>
    <nonDerivativeTransaction>
      <transactionDate><value>2026-07-10</value></transactionDate>
      <transactionCoding><transactionCode>P</transactionCode></transactionCoding>
      <transactionAmounts>
        <transactionShares><value>1000</value></transactionShares>
        <transactionPricePerShare><value>50</value></transactionPricePerShare>
      </transactionAmounts>
    </nonDerivativeTransaction>
    <nonDerivativeTransaction>
      <transactionDate><value>2026-07-11</value></transactionDate>
      <transactionCoding><transactionCode>A</transactionCode></transactionCoding>
      <transactionAmounts>
        <transactionShares><value>500</value></transactionShares>
        <transactionPricePerShare><value>0</value></transactionPricePerShare>
      </transactionAmounts>
    </nonDerivativeTransaction>
  </nonDerivativeTable>
</ownershipDocument>"""


def test_parse_form4() -> None:
    txns = parse_form4(FORM4_XML)
    assert len(txns) == 2
    buy = next(t for t in txns if t.transaction_type == InsiderTransactionType.BUY)
    assert buy.owner == "Jane Insider"
    assert buy.title == "CEO"
    assert buy.shares == 1000 and buy.price == 50
    assert buy.value == 50000
    grant = next(t for t in txns if t.transaction_type == InsiderTransactionType.GRANT)
    assert grant.transaction_type == InsiderTransactionType.GRANT


def test_analyze_scoring() -> None:
    today = date(2026, 7, 20)
    buys = [InsiderTransaction(transaction_date=date(2026, 7, 10), insider_name="A",
                               transaction_type=InsiderTransactionType.BUY, value=100000)]
    sells = [InsiderTransaction(transaction_date=date(2026, 7, 12), insider_name="B",
                                transaction_type=InsiderTransactionType.SELL, value=25000)]
    r = analyze(buys + sells, today)
    assert r.score == 80.0  # 100k buy / 125k total
    assert r.activity == "strong_buying"
    assert r.buy_count == 1 and r.sell_count == 1


def test_analyze_window_excludes_old() -> None:
    today = date(2026, 7, 20)
    old = [InsiderTransaction(transaction_date=date(2026, 1, 1), insider_name="A",
                              transaction_type=InsiderTransactionType.BUY, value=100000)]
    r = analyze(old, today, window=60)
    assert r.score is None and r.activity == "no_activity"


def _edgar_mock() -> httpx.Client:
    subs = {"filings": {"recent": {
        "form": ["4", "10-K"],
        "accessionNumber": ["0000000001-26-000001", "0000000001-26-000002"],
        "primaryDocument": ["form4.xml", "10k.htm"],
        "filingDate": ["2026-07-10", "2026-06-01"],
    }}}

    def handler(request: httpx.Request) -> httpx.Response:
        if "data.sec.gov/submissions" in str(request.url):
            return httpx.Response(200, content=json.dumps(subs))
        if request.url.path.endswith("form4.xml"):
            return httpx.Response(200, text=FORM4_XML)
        return httpx.Response(404)

    return httpx.Client(transport=httpx.MockTransport(handler))


def test_ingest_and_compute_end_to_end(db: Session) -> None:
    market = Market(code="NASDAQ", name="NASDAQ", region=MarketRegion.US,
                    currency="USD", ticker_suffix="")
    db.add(market)
    db.flush()
    sec = Security(market_id=market.id, symbol="AAPL", provider_symbol="AAPL",
                   name="Apple", asset_class=AssetClass.EQUITY, currency="USD",
                   cik="0000000001")
    db.add(sec)
    db.commit()

    n = ingest_insider_for_security(db, EdgarClient(_edgar_mock()), sec)
    db.commit()
    assert n == 2  # the buy + the grant were stored

    result = compute_for_security(db, sec, as_of=date(2026, 7, 20))
    assert result.score == 100.0        # only a buy counts for the signal
    assert result.activity == "strong_buying"

    summary = db.get(InsiderSummary, sec.id)
    assert summary is not None
    assert float(summary.score) == 100.0
    assert summary.activity == "strong_buying"


def test_no_cik_no_ingest(db: Session) -> None:
    market = Market(code="NASDAQ", name="NASDAQ", region=MarketRegion.US,
                    currency="USD", ticker_suffix="")
    db.add(market)
    db.flush()
    sec = Security(market_id=market.id, symbol="X", provider_symbol="X",
                   asset_class=AssetClass.EQUITY, currency="USD")  # no cik
    db.add(sec)
    db.commit()
    assert ingest_insider_for_security(db, EdgarClient(_edgar_mock()), sec) == 0
