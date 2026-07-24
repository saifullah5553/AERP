"""PSX fundamentals from stockanalysis.com CSV exports.

Consumes the per-company statement CSVs produced by the scraper
(``<TICKER>_Income_Statement.csv``, ``_Balance_Sheet.csv``, ``_Cash_Flow.csv``),
each holding ~20 quarterly TTM columns newest-first. We sample every 4th column
(so each point is a full trailing-year, one year apart) and store them as ANNUAL
statements — which the existing fundamental engine scores exactly like any other
market, with correct YoY growth and multi-year CAGR.

Monetary values are in millions (scaled to absolute); EPS/share counts as given.
Parsing works on CSV **text**, so it's unit-testable and source-agnostic (the same
code serves the folder today and a live scraper later).
"""

from __future__ import annotations

import csv
import io
from datetime import date, datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.ingestion.providers.base import StatementDTO
from app.ingestion.repository import upsert_statements
from app.models.enums import AssetClass, StatementPeriod
from app.models.market import Market, Security

log = get_logger(__name__)

MILLION = 1_000_000.0
# Sample columns 0,4,8,… → TTM snapshots one year apart → a clean annual series.
SAMPLE_IDX = (0, 4, 8, 12, 16)

# CSV label → (our column, scale). "m" = millions → absolute; "raw" = as-is.
INCOME_MAP = {
    "Revenue": ("revenue", "m"), "Cost of Revenue": ("cost_of_revenue", "m"),
    "Gross Profit": ("gross_profit", "m"), "Operating Income": ("operating_income", "m"),
    "EBITDA": ("ebitda", "m"), "Interest Expense": ("interest_expense", "m"),
    "Pretax Income": ("income_before_tax", "m"),
    "Income Tax Expense": ("income_tax_expense", "m"), "Net Income": ("net_income", "m"),
    "EPS (Basic)": ("eps", "raw"), "Shares Outstanding (Diluted)": ("weighted_shares", "m"),
}
BALANCE_MAP = {
    "Cash & Equivalents": ("cash_and_equivalents", "m"),
    "Short-Term Investments": ("short_term_investments", "m"),
    "Receivables": ("receivables", "m"), "Inventory": ("inventory", "m"),
    "Total Current Assets": ("current_assets", "m"), "Total Assets": ("total_assets", "m"),
    "Accounts Payable": ("accounts_payable", "m"), "Short-Term Debt": ("short_term_debt", "m"),
    "Total Current Liabilities": ("current_liabilities", "m"),
    "Long-Term Debt": ("long_term_debt", "m"), "Total Liabilities": ("total_liabilities", "m"),
    "Retained Earnings": ("retained_earnings", "m"),
    "Shareholders' Equity": ("total_equity", "m"), "Total Debt": ("total_debt", "m"),
}
CASHFLOW_MAP = {
    "Operating Cash Flow": ("operating_cash_flow", "m"),
    "Capital Expenditures": ("capital_expenditure", "m"),
    "Free Cash Flow": ("free_cash_flow", "m"),
    "Investing Cash Flow": ("investing_cash_flow", "m"),
    "Financing Cash Flow": ("financing_cash_flow", "m"),
    "Common Dividends Paid": ("dividends_paid", "m"),
    "Net Cash Flow": ("net_change_in_cash", "m"),
}
_STATEMENTS = [("income", INCOME_MAP), ("balance", BALANCE_MAP), ("cashflow", CASHFLOW_MAP)]
_SUFFIX = {
    "income": "_Income_Statement.csv",
    "balance": "_Balance_Sheet.csv",
    "cashflow": "_Cash_Flow.csv",
}


def _parse_date(text: str) -> date | None:
    try:
        return datetime.strptime(text.strip(), "%b %d, %Y").date()
    except ValueError:
        return None


def _parse_number(text: str) -> float | None:
    t = text.strip().replace(",", "")
    if not t or t in {"-", "—", "–"} or t.endswith("%"):
        return None
    try:
        return float(t)
    except ValueError:
        return None


def parse_statement_csv(text: str) -> tuple[list[date | None], dict[str, list[str]]]:
    """Return (period-end dates, {row label: value strings}) for one statement CSV."""
    rows = [r for r in csv.reader(io.StringIO(text)) if r]
    if not rows:
        return [], {}
    header = rows[0]
    try:
        pe = header.index("Period Ending")
    except ValueError:
        return [], {}
    n = pe - 1  # number of quarter columns
    dates = [_parse_date(d) for d in header[pe + 1: pe + 1 + n]]
    metrics = {r[0].strip(): r[1: 1 + n] for r in rows[1:]}
    return dates, metrics


def build_statements(
    income: str | None, balance: str | None, cashflow: str | None
) -> list[StatementDTO]:
    out: list[StatementDTO] = []
    for stype, text in (("income", income), ("balance", balance), ("cashflow", cashflow)):
        if not text:
            continue
        mapping = dict(_STATEMENTS)[stype]
        dates, metrics = parse_statement_csv(text)
        for idx in SAMPLE_IDX:
            if idx >= len(dates) or dates[idx] is None:
                continue
            values: dict[str, float] = {}
            for label, (col, scale) in mapping.items():
                series = metrics.get(label)
                if not series or idx >= len(series):
                    continue
                v = _parse_number(series[idx])
                if v is None:
                    continue
                values[col] = v * MILLION if scale == "m" else v
            if values:
                out.append(
                    StatementDTO(stype, dates[idx], StatementPeriod.ANNUAL,
                                 reported_currency="PKR", values=values)
                )
    return out


def ingest_ticker(
    db: Session,
    ticker: str,
    income: str | None,
    balance: str | None,
    cashflow: str | None,
    create_missing: bool = True,
) -> int:
    provider_symbol = f"{ticker}.KA"
    security = db.scalar(select(Security).where(Security.provider_symbol == provider_symbol))
    if security is None:
        if not create_missing:
            return 0
        psx = db.scalar(select(Market).where(Market.code == "PSX"))
        if psx is None:
            return 0
        security = Security(
            market_id=psx.id, symbol=ticker, provider_symbol=provider_symbol,
            asset_class=AssetClass.EQUITY, currency="PKR", country="PK", is_active=True,
        )
        db.add(security)
        db.flush()

    dtos = build_statements(income, balance, cashflow)
    if not dtos:
        return 0
    return upsert_statements(db, security.id, dtos)


def _read(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:  # pragma: no cover - IO dependent
        return None


def ingest_psx_csv(db: Session, csv_dir: Path | None = None) -> dict[str, int]:
    """Ingest every ticker's statement CSVs from the folder."""
    from app.core.config import settings

    directory = csv_dir or Path(settings.psx_csv_dir)
    if not directory.exists():
        log.warning("PSX CSV dir does not exist: %s", directory)
        return {"tickers": 0, "ingested": 0, "statements_written": 0}

    # Group files by ticker via the income-statement filename.
    tickers = sorted(
        p.name[: -len(_SUFFIX["income"])]
        for p in directory.glob(f"*{_SUFFIX['income']}")
    )
    ingested = 0
    written = 0
    for ticker in tickers:
        texts = {k: _read(directory / f"{ticker}{sfx}") for k, sfx in _SUFFIX.items()}
        n = ingest_ticker(db, ticker, texts["income"], texts["balance"], texts["cashflow"])
        if n:
            ingested += 1
            written += n
            db.commit()
    result = {"tickers": len(tickers), "ingested": ingested, "statements_written": written}
    log.info("ingest_psx_csv: %s", result)
    return result
