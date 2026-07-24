"""FMP provider — Financial Modeling Prep. Requires an API key.

Primary source for US equities (quotes, daily history, universe) and a fallback
for forex/commodities. Fundamentals ingestion (statements) is added in Phase 3
via this same provider.
"""

from __future__ import annotations

from datetime import UTC, date, datetime

from app.core.config import settings
from app.core.logging import get_logger
from app.ingestion.providers.base import (
    MarketDataProvider,
    OHLCVBar,
    QuoteDTO,
    SecurityProfile,
    StatementDTO,
)
from app.models.enums import AssetClass, MarketRegion, StatementPeriod

log = get_logger(__name__)

BASE_URL = "https://financialmodelingprep.com/api/v3"
US_EXCHANGES = {"NASDAQ", "NYSE", "AMEX"}

# FMP JSON key → our ORM column, per statement type.
_INCOME_MAP = {
    "revenue": "revenue", "costOfRevenue": "cost_of_revenue", "grossProfit": "gross_profit",
    "operatingExpenses": "operating_expenses", "operatingIncome": "operating_income",
    "ebitda": "ebitda", "interestExpense": "interest_expense",
    "incomeBeforeTax": "income_before_tax", "incomeTaxExpense": "income_tax_expense",
    "netIncome": "net_income", "eps": "eps", "epsdiluted": "eps_diluted",
    "weightedAverageShsOut": "weighted_shares",
}
_BALANCE_MAP = {
    "cashAndCashEquivalents": "cash_and_equivalents",
    "shortTermInvestments": "short_term_investments",
    "netReceivables": "receivables", "inventory": "inventory",
    "totalCurrentAssets": "current_assets", "propertyPlantEquipmentNet": "property_plant_equipment",
    "goodwillAndIntangibleAssets": "goodwill_intangibles", "totalAssets": "total_assets",
    "accountPayables": "accounts_payable", "shortTermDebt": "short_term_debt",
    "totalCurrentLiabilities": "current_liabilities", "longTermDebt": "long_term_debt",
    "totalDebt": "total_debt", "totalLiabilities": "total_liabilities",
    "retainedEarnings": "retained_earnings", "totalStockholdersEquity": "total_equity",
}
_CASHFLOW_MAP = {
    "operatingCashFlow": "operating_cash_flow", "capitalExpenditure": "capital_expenditure",
    "freeCashFlow": "free_cash_flow", "netCashUsedForInvestingActivites": "investing_cash_flow",
    "netCashUsedProvidedByFinancingActivities": "financing_cash_flow",
    "dividendsPaid": "dividends_paid", "commonStockRepurchased": "stock_repurchase",
    "netChangeInCash": "net_change_in_cash",
}


def _to_fmp(provider_symbol: str) -> str:
    # Forex "EURUSD=X" -> "EURUSD"; commodity "GC=F" -> "GC"; equities unchanged.
    return provider_symbol.replace("=X", "").replace("=F", "")


class FMPProvider(MarketDataProvider):
    name = "fmp"

    @property
    def available(self) -> bool:
        return bool(settings.fmp_api_key)

    def supports(self, asset_class: AssetClass, region: MarketRegion) -> bool:
        return asset_class in {
            AssetClass.EQUITY,
            AssetClass.ETF,
            AssetClass.FOREX,
            AssetClass.COMMODITY,
            AssetClass.INDEX,
        }

    def _params(self, extra: dict | None = None) -> dict:
        params = {"apikey": settings.fmp_api_key}
        if extra:
            params.update(extra)
        return params

    def get_quotes(self, provider_symbols: list[str]) -> dict[str, QuoteDTO]:
        if not provider_symbols or not self.available:
            return {}
        rev = {_to_fmp(s): s for s in provider_symbols}
        joined = ",".join(rev.keys())
        try:
            resp = self._http().get(f"{BASE_URL}/quote/{joined}", params=self._params())
            resp.raise_for_status()
            rows = resp.json()
        except Exception as exc:
            log.warning("FMP quotes failed: %s", exc)
            return {}

        out: dict[str, QuoteDTO] = {}
        for row in rows if isinstance(rows, list) else []:
            fsym = row.get("symbol")
            provider_symbol = rev.get(fsym)
            if provider_symbol is None or row.get("price") is None:
                continue
            ts = row.get("timestamp")
            quoted_at = datetime.fromtimestamp(ts, tz=UTC) if ts else datetime.now(UTC)
            out[provider_symbol] = QuoteDTO(
                provider_symbol=provider_symbol,
                price=float(row["price"]),
                prev_close=_f(row.get("previousClose")),
                change=_f(row.get("change")),
                change_pct=_f(row.get("changesPercentage")),
                day_open=_f(row.get("open")),
                day_high=_f(row.get("dayHigh")),
                day_low=_f(row.get("dayLow")),
                volume=_i(row.get("volume")),
                quoted_at=quoted_at,
            ).filled()
        return out

    def get_daily(self, provider_symbol: str, start: date | None = None) -> list[OHLCVBar]:
        if not self.available:
            return []
        extra = {"from": start.isoformat()} if start else {"serietype": "line"}
        fsym = _to_fmp(provider_symbol)
        try:
            resp = self._http().get(
                f"{BASE_URL}/historical-price-full/{fsym}", params=self._params(extra)
            )
            resp.raise_for_status()
            data = resp.json()
        except Exception as exc:
            log.warning("FMP history failed for %s: %s", provider_symbol, exc)
            return []

        bars: list[OHLCVBar] = []
        for row in reversed(data.get("historical", [])):  # FMP returns newest-first
            try:
                bars.append(
                    OHLCVBar(
                        date=date.fromisoformat(row["date"]),
                        open=_f(row.get("open")),
                        high=_f(row.get("high")),
                        low=_f(row.get("low")),
                        close=float(row["close"]),
                        adj_close=_f(row.get("adjClose")),
                        volume=_i(row.get("volume")),
                    )
                )
            except (KeyError, TypeError, ValueError):
                continue
        return bars

    def list_universe(self) -> list[SecurityProfile]:
        if not self.available:
            return []
        try:
            resp = self._http().get(f"{BASE_URL}/stock/list", params=self._params())
            resp.raise_for_status()
            rows = resp.json()
        except Exception as exc:
            log.warning("FMP stock list failed: %s", exc)
            return []

        profiles: list[SecurityProfile] = []
        for row in rows if isinstance(rows, list) else []:
            if row.get("exchangeShortName") not in US_EXCHANGES:
                continue
            if row.get("type") not in {"stock", None}:
                continue
            sym = row.get("symbol")
            if not sym or "." in sym:  # skip preferred/warrant class suffixes
                continue
            profiles.append(
                SecurityProfile(
                    symbol=sym,
                    name=row.get("name"),
                    asset_class=AssetClass.EQUITY,
                    exchange=row.get("exchangeShortName"),
                    currency="USD",
                    country="US",
                )
            )
        return profiles


    def get_statements(
        self, provider_symbol: str, period: StatementPeriod, limit: int = 5
    ) -> list[StatementDTO]:
        if not self.available:
            return []
        fsym = _to_fmp(provider_symbol)
        fmp_period = "quarter" if period == StatementPeriod.QUARTER else "annual"
        endpoints = {
            "income": ("income-statement", _INCOME_MAP),
            "balance": ("balance-sheet-statement", _BALANCE_MAP),
            "cashflow": ("cash-flow-statement", _CASHFLOW_MAP),
        }
        out: list[StatementDTO] = []
        for stmt_type, (path, mapping) in endpoints.items():
            try:
                resp = self._http().get(
                    f"{BASE_URL}/{path}/{fsym}",
                    params=self._params({"period": fmp_period, "limit": limit}),
                )
                resp.raise_for_status()
                rows = resp.json()
            except Exception as exc:
                log.warning("FMP %s failed for %s: %s", stmt_type, provider_symbol, exc)
                continue
            for row in rows if isinstance(rows, list) else []:
                raw_date = row.get("date")
                if not raw_date:
                    continue
                values = {col: _f(row.get(key)) for key, col in mapping.items()}
                if stmt_type == "income":
                    # EBIT ≈ pre-tax income + interest expense; fall back to op. income.
                    ibt = _f(row.get("incomeBeforeTax"))
                    interest = _f(row.get("interestExpense"))
                    if ibt is not None and interest is not None:
                        values["ebit"] = ibt + interest
                    else:
                        values["ebit"] = _f(row.get("operatingIncome"))
                out.append(
                    StatementDTO(
                        statement_type=stmt_type,
                        fiscal_date=date.fromisoformat(raw_date[:10]),
                        period=period,
                        reported_currency=row.get("reportedCurrency"),
                        values=values,
                    )
                )
        return out


def _f(value) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _i(value) -> int | None:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None
