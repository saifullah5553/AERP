"""Yahoo Finance provider (keyless) via the ``yfinance`` library.

This is the universal free source: the platform already uses Yahoo-style provider
symbols (``AAPL``, ``RELIANCE.NS``, ``2222.SR``, ``EURUSD=X``, ``GC=F``,
``BTC-USD``), so one provider covers US / India / GCC equities plus forex,
commodities, and crypto — with quotes, daily history, AND fundamentals, no API key.

Design for testability + resilience:
- All network/pandas work lives behind the injectable :class:`YahooFetcher`
  interface. :class:`YFinanceFetcher` is the real implementation (lazy-imports
  ``yfinance`` so this module imports fine without it); tests inject a fake fetcher
  returning canned primitives, so no network and no yfinance are needed to test.
- Yahoo is an unofficial source and can rate-limit datacenter IPs; every call is
  guarded and simply yields nothing on failure (never fabricates).
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any, Protocol, runtime_checkable

from app.core.logging import get_logger
from app.ingestion.providers.base import (
    MarketDataProvider,
    OHLCVBar,
    QuoteDTO,
    StatementDTO,
)
from app.models.enums import AssetClass, MarketRegion, StatementPeriod

log = get_logger(__name__)

STATEMENT_TYPES = ("income", "balance", "cashflow")


@runtime_checkable
class YahooFetcher(Protocol):
    """Returns already-normalised primitives (no pandas) keyed to our columns."""

    def quotes(self, symbols: list[str]) -> dict[str, dict[str, Any]]: ...
    def daily(self, symbol: str, start: date | None) -> list[dict[str, Any]]: ...
    def statements(self, symbol: str) -> dict[str, list[dict[str, Any]]]: ...


# Yahoo statement row labels → our ORM statement columns. Used only by the real
# YFinanceFetcher; centralised here so the mapping is easy to audit/adjust.
Y_INCOME = {
    "Total Revenue": "revenue", "Cost Of Revenue": "cost_of_revenue",
    "Gross Profit": "gross_profit", "Operating Income": "operating_income",
    "EBITDA": "ebitda", "EBIT": "ebit", "Interest Expense": "interest_expense",
    "Pretax Income": "income_before_tax", "Tax Provision": "income_tax_expense",
    "Net Income": "net_income", "Basic EPS": "eps", "Diluted EPS": "eps_diluted",
    "Basic Average Shares": "weighted_shares",
}
Y_BALANCE = {
    "Total Assets": "total_assets", "Current Assets": "current_assets",
    "Cash And Cash Equivalents": "cash_and_equivalents", "Inventory": "inventory",
    "Current Liabilities": "current_liabilities", "Total Debt": "total_debt",
    "Long Term Debt": "long_term_debt", "Current Debt": "short_term_debt",
    "Total Liabilities Net Minority Interest": "total_liabilities",
    "Retained Earnings": "retained_earnings", "Stockholders Equity": "total_equity",
    "Accounts Payable": "accounts_payable",
}
Y_CASHFLOW = {
    "Operating Cash Flow": "operating_cash_flow",
    "Capital Expenditure": "capital_expenditure", "Free Cash Flow": "free_cash_flow",
    "Cash Dividends Paid": "dividends_paid", "Investing Cash Flow": "investing_cash_flow",
    "Financing Cash Flow": "financing_cash_flow",
    "Repurchase Of Capital Stock": "stock_repurchase", "Changes In Cash": "net_change_in_cash",
}


class YahooProvider(MarketDataProvider):
    name = "yahoo"

    def __init__(self, fetcher: YahooFetcher | None = None, client: Any = None) -> None:
        super().__init__(client)
        self._fetcher = fetcher or YFinanceFetcher()

    @property
    def available(self) -> bool:
        return True  # keyless

    def supports(self, asset_class: AssetClass, region: MarketRegion) -> bool:
        return True  # universal fallback for every asset class / region

    def get_quotes(self, provider_symbols: list[str]) -> dict[str, QuoteDTO]:
        if not provider_symbols:
            return {}
        try:
            raw = self._fetcher.quotes(provider_symbols)
        except Exception as exc:  # pragma: no cover - network dependent
            log.warning("Yahoo quotes failed: %s", exc)
            return {}
        out: dict[str, QuoteDTO] = {}
        now = datetime.now(UTC)
        for sym, q in raw.items():
            price = q.get("price")
            if price is None:
                continue
            out[sym] = QuoteDTO(
                provider_symbol=sym,
                price=float(price),
                prev_close=_f(q.get("prev_close")),
                day_open=_f(q.get("open")),
                day_high=_f(q.get("high")),
                day_low=_f(q.get("low")),
                volume=_i(q.get("volume")),
                quoted_at=now,
            ).filled()
        return out

    def get_daily(self, provider_symbol: str, start: date | None = None) -> list[OHLCVBar]:
        try:
            rows = self._fetcher.daily(provider_symbol, start)
        except Exception as exc:  # pragma: no cover - network dependent
            log.warning("Yahoo daily failed for %s: %s", provider_symbol, exc)
            return []
        bars: list[OHLCVBar] = []
        for r in rows:
            try:
                bars.append(
                    OHLCVBar(
                        date=date.fromisoformat(r["date"]),
                        open=_f(r.get("open")),
                        high=_f(r.get("high")),
                        low=_f(r.get("low")),
                        close=float(r["close"]),
                        adj_close=_f(r.get("adj_close")),
                        volume=_i(r.get("volume")),
                    )
                )
            except (KeyError, TypeError, ValueError):
                continue
        return bars

    def get_statements(
        self, provider_symbol: str, period: StatementPeriod, limit: int = 5
    ) -> list[StatementDTO]:
        if period != StatementPeriod.ANNUAL:
            return []  # only annual statements from Yahoo for now
        try:
            data = self._fetcher.statements(provider_symbol)
        except Exception as exc:  # pragma: no cover - network dependent
            log.warning("Yahoo statements failed for %s: %s", provider_symbol, exc)
            return []
        out: list[StatementDTO] = []
        for stype in STATEMENT_TYPES:
            for row in data.get(stype, [])[:limit]:
                raw_date = row.get("fiscal_date")
                if not raw_date:
                    continue
                out.append(
                    StatementDTO(
                        statement_type=stype,
                        fiscal_date=date.fromisoformat(raw_date),
                        period=StatementPeriod.ANNUAL,
                        reported_currency=row.get("reported_currency"),
                        values={k: _f(v) for k, v in row.get("values", {}).items()},
                    )
                )
        return out


class YFinanceFetcher:
    """Real fetcher backed by ``yfinance`` (lazy-imported)."""

    def __init__(self) -> None:
        self._yf: Any = None

    def _lib(self) -> Any:
        if self._yf is None:
            import yfinance as yf  # lazy: not needed unless a live fetch happens

            self._yf = yf
        return self._yf

    def quotes(self, symbols: list[str]) -> dict[str, dict[str, Any]]:
        yf = self._lib()
        out: dict[str, dict[str, Any]] = {}
        for sym in symbols:
            try:
                fi = yf.Ticker(sym).fast_info
                price = _attr(fi, "last_price")
                if price is None:
                    continue
                out[sym] = {
                    "price": price,
                    "prev_close": _attr(fi, "previous_close"),
                    "open": _attr(fi, "open"),
                    "high": _attr(fi, "day_high"),
                    "low": _attr(fi, "day_low"),
                    "volume": _attr(fi, "last_volume"),
                }
            except Exception:  # pragma: no cover - network dependent
                continue
        return out

    def daily(self, symbol: str, start: date | None) -> list[dict[str, Any]]:
        yf = self._lib()
        ticker = yf.Ticker(symbol)
        kwargs: dict[str, Any] = {"interval": "1d", "auto_adjust": False}
        if start:
            kwargs["start"] = start.isoformat()
        else:
            kwargs["period"] = "2y"
        df = ticker.history(**kwargs)
        rows: list[dict[str, Any]] = []
        for idx, row in df.iterrows():
            rows.append(
                {
                    "date": idx.date().isoformat(),
                    "open": row.get("Open"),
                    "high": row.get("High"),
                    "low": row.get("Low"),
                    "close": row.get("Close"),
                    "adj_close": row.get("Adj Close", row.get("Close")),
                    "volume": row.get("Volume"),
                }
            )
        return rows

    def statements(self, symbol: str) -> dict[str, list[dict[str, Any]]]:
        yf = self._lib()
        ticker = yf.Ticker(symbol)
        return {
            "income": _frame_to_rows(getattr(ticker, "income_stmt", None), Y_INCOME),
            "balance": _frame_to_rows(getattr(ticker, "balance_sheet", None), Y_BALANCE),
            "cashflow": _frame_to_rows(getattr(ticker, "cashflow", None), Y_CASHFLOW),
        }


def _frame_to_rows(df: Any, label_map: dict[str, str]) -> list[dict[str, Any]]:
    """Convert a yfinance statement DataFrame (labels × period columns) to rows."""
    if df is None or getattr(df, "empty", True):
        return []
    rows: list[dict[str, Any]] = []
    for col in df.columns:
        values: dict[str, Any] = {}
        for label, our_col in label_map.items():
            if label in df.index:
                val = df.at[label, col]
                if val is not None and not _is_nan(val):
                    values[our_col] = float(val)
        if values:
            rows.append({"fiscal_date": col.date().isoformat(), "values": values})
    return rows


def _attr(obj: Any, name: str) -> Any:
    try:
        return obj[name]
    except Exception:
        return getattr(obj, name, None)


def _is_nan(v: Any) -> bool:
    try:
        return v != v  # NaN is the only value not equal to itself
    except Exception:
        return False


def _f(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _i(value: Any) -> int | None:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None
