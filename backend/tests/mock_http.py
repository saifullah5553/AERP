"""A mock HTTP layer for provider/pipeline tests.

Builds an ``httpx.Client`` whose transport dispatches by host+path and returns
canned provider payloads — no network, fully deterministic.
"""

from __future__ import annotations

import json

import httpx

# ── Canned payloads ───────────────────────────────────────────
_BINANCE_TICKERS = {
    "BTCUSDT": {
        "symbol": "BTCUSDT", "lastPrice": "65000.0", "prevClosePrice": "64000.0",
        "priceChange": "1000.0", "priceChangePercent": "1.5625", "openPrice": "64000.0",
        "highPrice": "66000.0", "lowPrice": "63500.0", "volume": "12345.0",
    },
    "ETHUSDT": {
        "symbol": "ETHUSDT", "lastPrice": "3200.0", "prevClosePrice": "3150.0",
        "priceChange": "50.0", "priceChangePercent": "1.5873", "openPrice": "3150.0",
        "highPrice": "3250.0", "lowPrice": "3100.0", "volume": "54321.0",
    },
}

_BINANCE_KLINES = [
    [1690156800000, "63000", "64500", "62800", "64000", "10000", 1690243199999],
    [1690243200000, "64000", "66000", "63500", "65000", "12345", 1690329599999],
]

_BINANCE_EXCHANGE_INFO = {
    "symbols": [
        {"symbol": "BTCUSDT", "status": "TRADING", "baseAsset": "BTC", "quoteAsset": "USDT"},
        {"symbol": "ETHUSDT", "status": "TRADING", "baseAsset": "ETH", "quoteAsset": "USDT"},
        {"symbol": "XRPBTC", "status": "TRADING", "baseAsset": "XRP", "quoteAsset": "BTC"},
        {"symbol": "OLDUSDT", "status": "BREAK", "baseAsset": "OLD", "quoteAsset": "USDT"},
    ]
}

PSX_HTML = """
<table><tbody>
<tr><td><a href="/company/LUCK">LUCK</a></td>
    <td class="current">445.63</td><td class="change">2.50</td><td class="volume">1,234,567</td></tr>
<tr><td><a href="/company/OGDC">OGDC</a></td>
    <td class="current">210.00</td><td class="change">-1.20</td><td class="volume">987,654</td></tr>
</tbody></table>
"""

_FMP_QUOTES = {
    "AAPL": {
        "symbol": "AAPL", "price": 200.0, "previousClose": 196.0, "change": 4.0,
        "changesPercentage": 2.04, "open": 197.0, "dayHigh": 201.0, "dayLow": 196.0,
        "volume": 50000000, "timestamp": 1690240000,
    },
}

_FMP_HISTORY = {
    "symbol": "AAPL",
    "historical": [
        {"date": "2026-07-24", "open": 197.0, "high": 201.0, "low": 196.0,
         "close": 200.0, "adjClose": 200.0, "volume": 50000000},
        {"date": "2026-07-23", "open": 195.0, "high": 198.0, "low": 194.0,
         "close": 196.0, "adjClose": 196.0, "volume": 48000000},
    ],
}

_FMP_STOCK_LIST = [
    {"symbol": "AAPL", "name": "Apple Inc.", "exchangeShortName": "NASDAQ", "type": "stock"},
    {"symbol": "MSFT", "name": "Microsoft", "exchangeShortName": "NASDAQ", "type": "stock"},
    {"symbol": "IBM", "name": "IBM", "exchangeShortName": "NYSE", "type": "stock"},
    {"symbol": "PENNY", "name": "Penny", "exchangeShortName": "OTC", "type": "stock"},
    {"symbol": "BRK.B", "name": "Berkshire B", "exchangeShortName": "NYSE", "type": "stock"},
]

_TD_QUOTE = {
    "symbol": "EUR/USD", "name": "Euro US Dollar", "close": "1.0850",
    "previous_close": "1.0830", "change": "0.0020", "percent_change": "0.1846",
    "open": "1.0835", "high": "1.0860", "low": "1.0825", "volume": "0",
}

_TD_TIMESERIES = {
    "status": "ok",
    "values": [
        {"datetime": "2026-07-24", "open": "1.0835", "high": "1.0860",
         "low": "1.0825", "close": "1.0850", "volume": "0"},
        {"datetime": "2026-07-23", "open": "1.0820", "high": "1.0840",
         "low": "1.0810", "close": "1.0830", "volume": "0"},
    ],
}


def _json(payload) -> httpx.Response:
    return httpx.Response(200, content=json.dumps(payload), headers={"content-type": "application/json"})


def _handler(request: httpx.Request) -> httpx.Response:
    host = request.url.host
    path = request.url.path

    if host == "api.binance.com":
        if path == "/api/v3/ticker/24hr":
            symbols = json.loads(request.url.params.get("symbols", "[]"))
            return _json([_BINANCE_TICKERS[s] for s in symbols if s in _BINANCE_TICKERS])
        if path == "/api/v3/klines":
            return _json(_BINANCE_KLINES)
        if path == "/api/v3/exchangeInfo":
            return _json(_BINANCE_EXCHANGE_INFO)

    if host == "dps.psx.com.pk" and path == "/all":
        return httpx.Response(200, text=PSX_HTML)

    if "financialmodelingprep.com" in host:
        if path.startswith("/api/v3/quote/"):
            wanted = path.rsplit("/", 1)[1].split(",")
            return _json([_FMP_QUOTES[s] for s in wanted if s in _FMP_QUOTES])
        if path.startswith("/api/v3/historical-price-full/"):
            return _json(_FMP_HISTORY)
        if path == "/api/v3/stock/list":
            return _json(_FMP_STOCK_LIST)

    if host == "api.twelvedata.com":
        if path == "/quote":
            return _json(_TD_QUOTE)
        if path == "/time_series":
            return _json(_TD_TIMESERIES)

    return httpx.Response(404, text=f"unmocked: {host}{path}")


def mock_client() -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(_handler))
