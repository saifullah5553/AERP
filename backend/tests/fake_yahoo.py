"""A canned YahooFetcher for tests — no network, no yfinance needed.

Returns the same normalised primitives the real YFinanceFetcher would, so the
YahooProvider mapping and the whole ingestion pipeline can be tested deterministically.
"""

from __future__ import annotations

from datetime import date
from typing import Any

_DEFAULT_QUOTES: dict[str, dict[str, Any]] = {
    "AAPL": {"price": 200.0, "prev_close": 196.0, "open": 197.0, "high": 201.0,
             "low": 196.0, "volume": 50_000_000},
    "EURUSD=X": {"price": 1.0850, "prev_close": 1.0830, "open": 1.0835, "high": 1.0860,
                 "low": 1.0825, "volume": 0},
    "RELIANCE.NS": {"price": 2900.0, "prev_close": 2880.0, "open": 2885.0, "high": 2910.0,
                    "low": 2870.0, "volume": 1_000_000},
    "GC=F": {"price": 2400.0, "prev_close": 2390.0, "open": 2392.0, "high": 2405.0,
             "low": 2388.0, "volume": 120_000},
    "XYZ.KA": {"price": 55.0, "prev_close": 54.0, "open": 54.2, "high": 55.5,
               "low": 53.9, "volume": 200_000},
}

_DEFAULT_DAILY: dict[str, list[dict[str, Any]]] = {
    "AAPL": [
        {"date": "2026-07-23", "open": 195.0, "high": 198.0, "low": 194.0,
         "close": 196.0, "adj_close": 196.0, "volume": 48_000_000},
        {"date": "2026-07-24", "open": 197.0, "high": 201.0, "low": 196.0,
         "close": 200.0, "adj_close": 200.0, "volume": 50_000_000},
    ],
    "EURUSD=X": [
        {"date": "2026-07-23", "open": 1.082, "high": 1.084, "low": 1.081,
         "close": 1.083, "adj_close": 1.083, "volume": 0},
        {"date": "2026-07-24", "open": 1.0835, "high": 1.086, "low": 1.0825,
         "close": 1.085, "adj_close": 1.085, "volume": 0},
    ],
}

_DEFAULT_STATEMENTS: dict[str, dict[str, list[dict[str, Any]]]] = {
    "AAPL": {
        "income": [
            {"fiscal_date": "2025-12-31", "values": {
                "revenue": 1200, "gross_profit": 500, "operating_income": 320,
                "ebitda": 380, "ebit": 320, "interest_expense": 25,
                "income_before_tax": 295, "income_tax_expense": 59, "net_income": 236,
                "eps": 2.36, "weighted_shares": 100}},
            {"fiscal_date": "2024-12-31", "values": {
                "revenue": 1000, "gross_profit": 400, "operating_income": 250,
                "net_income": 184, "eps": 1.84, "weighted_shares": 100}},
        ],
        "balance": [
            {"fiscal_date": "2025-12-31", "values": {
                "total_assets": 2200, "current_assets": 900, "current_liabilities": 420,
                "inventory": 210, "total_debt": 480, "total_equity": 1150,
                "cash_and_equivalents": 200, "retained_earnings": 750,
                "total_liabilities": 1050}},
            {"fiscal_date": "2024-12-31", "values": {
                "total_assets": 2000, "total_equity": 1000, "total_debt": 500}},
        ],
        "cashflow": [
            {"fiscal_date": "2025-12-31", "values": {
                "operating_cash_flow": 300, "capital_expenditure": -90,
                "free_cash_flow": 210, "dividends_paid": -60}},
            {"fiscal_date": "2024-12-31", "values": {
                "operating_cash_flow": 250, "free_cash_flow": 170}},
        ],
    },
}


class FakeYahooFetcher:
    def __init__(
        self,
        quotes: dict[str, dict[str, Any]] | None = None,
        daily: dict[str, list[dict[str, Any]]] | None = None,
        statements: dict[str, dict[str, list[dict[str, Any]]]] | None = None,
    ) -> None:
        self._quotes = _DEFAULT_QUOTES if quotes is None else quotes
        self._daily = _DEFAULT_DAILY if daily is None else daily
        self._statements = _DEFAULT_STATEMENTS if statements is None else statements

    def quotes(self, symbols: list[str]) -> dict[str, dict[str, Any]]:
        return {s: self._quotes[s] for s in symbols if s in self._quotes}

    def daily(self, symbol: str, start: date | None) -> list[dict[str, Any]]:
        return self._daily.get(symbol, [])

    def statements(self, symbol: str) -> dict[str, list[dict[str, Any]]]:
        return self._statements.get(symbol, {"income": [], "balance": [], "cashflow": []})
