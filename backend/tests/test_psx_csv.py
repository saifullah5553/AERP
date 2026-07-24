from __future__ import annotations

from datetime import date

from app.engines.fundamental.engine import compute_for_security
from app.ingestion.psx_csv import build_statements, ingest_ticker, parse_statement_csv
from app.models.enums import AssetClass, MarketRegion
from app.models.fundamentals import IncomeStatement
from app.models.market import Market, Security
from sqlalchemy import func, select
from sqlalchemy.orm import Session

# Mirrors the real stockanalysis.com layout: quarter labels, a "Period Ending"
# marker, then the period-end dates (newest first). 5 quarters here.
HEADER = ('Fiscal Quarter,Q3 2026,Q2 2026,Q1 2026,Q4 2025,Q3 2025,Period Ending,'
          '"Mar 31, 2026","Dec 31, 2025","Sep 30, 2025","Jun 30, 2025","Mar 31, 2025"')

INCOME = HEADER + "\n" + "\n".join([
    'Revenue,"1,200","1,150","1,100","1,050","1,000"',
    "Net Income,236,220,210,200,190",
    "EBITDA,380,370,360,350,340",
    "Interest Expense,-25,-24,-23,-22,-20",
    "Pretax Income,295,280,270,260,250",
    "EPS (Basic),2.36,2.20,2.10,2.00,1.90",
    "Shares Outstanding (Diluted),100,100,100,100,100",
])
BALANCE = HEADER + "\n" + "\n".join([
    'Total Assets,"2,200","2,150","2,100","2,050","2,000"',
    "Shareholders' Equity,\"1,150\",\"1,120\",\"1,090\",\"1,050\",\"1,000\"",
    "Total Debt,480,485,490,495,500",
    "Total Current Assets,900,880,860,840,800",
    "Total Current Liabilities,420,418,415,410,400",
    "Inventory,210,208,205,203,200",
    "Cash & Equivalents,200,195,190,185,150",
    "Retained Earnings,750,730,710,690,600",
])
CASHFLOW = HEADER + "\n" + "\n".join([
    "Operating Cash Flow,300,290,280,270,250",
    "Capital Expenditures,-90,-88,-86,-84,-80",
    "Free Cash Flow,210,202,194,186,170",
    "Common Dividends Paid,-60,-58,-56,-54,-50",
])


def _psx_market(db: Session) -> Market:
    m = Market(code="PSX", name="PSX", region=MarketRegion.PSX,
               currency="PKR", ticker_suffix=".KA")
    db.add(m)
    db.commit()
    return m


def test_parse_header_and_dates() -> None:
    dates, metrics = parse_statement_csv(INCOME)
    assert dates[0] == date(2026, 3, 31)
    assert dates[4] == date(2025, 3, 31)
    assert metrics["Revenue"][0] == "1,200"


def test_build_statements_samples_and_scales() -> None:
    dtos = build_statements(INCOME, BALANCE, CASHFLOW)
    income = [d for d in dtos if d.statement_type == "income"]
    # Only idx 0 and 4 exist among (0,4,8,12,16) for a 5-column file → 2 annual points.
    assert {d.fiscal_date for d in income} == {date(2026, 3, 31), date(2025, 3, 31)}
    latest = max(income, key=lambda d: d.fiscal_date)
    assert latest.values["revenue"] == 1_200 * 1_000_000  # millions → absolute
    assert latest.values["net_income"] == 236 * 1_000_000
    assert latest.values["eps"] == 2.36  # per-share, not scaled


def test_ingest_ticker_writes_statements(db: Session) -> None:
    _psx_market(db)
    db.add(Security(market_id=1, symbol="LUCK", provider_symbol="LUCK.KA",
                    name="Lucky", asset_class=AssetClass.EQUITY, currency="PKR"))
    db.commit()

    written = ingest_ticker(db, "LUCK", INCOME, BALANCE, CASHFLOW)
    db.commit()
    assert written > 0
    sec = db.scalar(select(Security).where(Security.provider_symbol == "LUCK.KA"))
    income_rows = db.scalar(
        select(func.count()).select_from(IncomeStatement).where(
            IncomeStatement.security_id == sec.id
        )
    )
    assert income_rows == 2


def test_ingest_auto_creates_missing_security(db: Session) -> None:
    _psx_market(db)
    written = ingest_ticker(db, "NEWCO", INCOME, BALANCE, CASHFLOW)
    assert written > 0
    assert db.scalar(select(Security).where(Security.provider_symbol == "NEWCO.KA")) is not None


def test_end_to_end_psx_fundamental_score(db: Session) -> None:
    _psx_market(db)
    ingest_ticker(db, "LUCK", INCOME, BALANCE, CASHFLOW)
    db.commit()
    sec = db.scalar(select(Security).where(Security.provider_symbol == "LUCK.KA"))

    outcome = compute_for_security(db, sec)  # the SAME engine as US equities
    assert outcome.computed is True
    assert outcome.score is not None
