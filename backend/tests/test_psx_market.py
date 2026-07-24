from __future__ import annotations

import httpx
from app.ingestion.psx_market import (
    PSXPortalClient,
    ingest_psx_market,
    parse_eod,
    parse_market_watch,
    parse_symbols,
)
from app.models.enums import AssetClass, MarketRegion
from app.models.market import Market, Security
from app.models.prices import DailyPrice
from app.models.quote import Quote
from sqlalchemy import select
from sqlalchemy.orm import Session

SYMBOLS_JSON = (
    '[{"symbol":"LUCK","name":"Lucky Cement Limited","sectorName":"CEMENT",'
    '"isETF":false,"isDebt":false},'
    '{"symbol":"AKBLTFC6","name":"Askari Bank(TFC6)","sectorName":"BILLS AND BONDS",'
    '"isETF":false,"isDebt":true}]'
)

MARKET_WATCH_HTML = """
<table><tbody>
<tr><td>LUCK</td><td>0812</td><td>KSE100</td><td>430.00</td><td>431.00</td>
    <td>435.50</td><td>428.10</td><td>433.01</td><td>3.01</td><td>0.70%</td>
    <td>2,056,126</td></tr>
<tr><td>FFC</td><td>0801</td><td>KSE100</td><td>550.00</td><td>551.00</td>
    <td>560.00</td><td>549.00</td><td>555.00</td><td>5.00</td><td>0.91%</td>
    <td>1,000,000</td></tr>
</tbody></table>
"""

# [ts, adjusted_close, volume, raw_close]
EOD_JSON = (
    '{"status":1,"message":"","data":['
    '[1784890800,433.01,2056126,431],'
    '[1784804400,430.00,1500000,429],'
    '[1784718000,428.50,1200000,427]]}'
)


def test_parse_symbols() -> None:
    meta = parse_symbols(SYMBOLS_JSON)
    assert meta["LUCK"].name == "Lucky Cement Limited"
    assert meta["LUCK"].sector == "CEMENT"
    assert meta["AKBLTFC6"].is_debt is True


def test_parse_market_watch() -> None:
    rows = parse_market_watch(MARKET_WATCH_HTML)
    assert len(rows) == 2
    luck = rows[0]
    assert luck.symbol == "LUCK"
    assert luck.close == 433.01
    assert luck.ldcp == 430.00
    assert luck.change_pct == 0.70
    assert luck.volume == 2_056_126


def test_parse_eod_uses_adjusted_close_and_sorts() -> None:
    bars = parse_eod(EOD_JSON)
    assert len(bars) == 3
    # sorted ascending by date
    assert bars[0].date < bars[-1].date
    # adjusted close (index 1), not raw close (index 3)
    assert bars[-1].close == 433.01
    assert bars[-1].volume == 2_056_126


def test_parse_bad_payloads_are_empty() -> None:
    assert parse_symbols("not json") == {}
    assert parse_eod("not json") == []
    assert parse_market_watch("<table><tbody></tbody></table>") == []


def _handler(request: httpx.Request) -> httpx.Response:
    path = request.url.path
    if path == "/symbols":
        return httpx.Response(200, text=SYMBOLS_JSON)
    if path == "/market-watch":
        return httpx.Response(200, text=MARKET_WATCH_HTML)
    if path.startswith("/timeseries/eod/"):
        return httpx.Response(200, text=EOD_JSON)
    return httpx.Response(404)


def _seed(db: Session) -> None:
    db.add(Market(code="PSX", name="PSX", region=MarketRegion.PSX,
                  currency="PKR", ticker_suffix=".KA"))
    db.add(Security(market_id=1, symbol="LUCK", provider_symbol="LUCK.KA",
                    asset_class=AssetClass.EQUITY, currency="PKR"))
    db.commit()


def test_ingest_fills_name_quote_and_history(db: Session) -> None:
    _seed(db)
    client = PSXPortalClient(
        httpx.Client(base_url="https://dps.psx.com.pk",
                     transport=httpx.MockTransport(_handler))
    )
    result = ingest_psx_market(db, client)

    sec = db.scalar(select(Security).where(Security.symbol == "LUCK"))
    assert sec.name == "Lucky Cement Limited"
    assert sec.sector == "CEMENT"

    quote = db.get(Quote, sec.id)
    assert float(quote.price) == 433.01
    assert quote.volume == 2_056_126

    bars = db.scalars(
        select(DailyPrice).where(DailyPrice.security_id == sec.id)
    ).all()
    # 3 history bars (one shares today's date with the live bar → deduped by date).
    assert len(bars) >= 3
    assert result["named"] == 1
    assert result["quoted"] == 1
