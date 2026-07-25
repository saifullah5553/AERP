"""Trailing-twelve-month (TTM) statements built from stored quarterly data.

For every quarter with 4 trailing quarters available we produce a TTM row:
income & cash-flow lines are *summed* over the 4 quarters (they're flows), while
the balance sheet is a *point-in-time* snapshot so we carry each quarter's balance
through as-is. Stored under ``StatementPeriod.TTM`` alongside the raw quarterly rows,
so the platform can display current-through-latest-quarter figures that are still
comparable to a full year.
"""

from __future__ import annotations

from sqlalchemy import Numeric, select
from sqlalchemy.orm import Session

from app.ingestion.providers.base import StatementDTO
from app.ingestion.repository import upsert_statements
from app.models.enums import StatementPeriod
from app.models.fundamentals import BalanceSheet, CashFlowStatement, IncomeStatement

_FLOW_MODELS = {"income": IncomeStatement, "cashflow": CashFlowStatement}
_STOCK_MODELS = {"balance": BalanceSheet}
_META = {"id", "security_id", "fiscal_date", "period", "reported_currency",
         "created_at", "updated_at"}


def _numeric_columns(model) -> list[str]:
    return [
        c.name for c in model.__table__.columns
        if isinstance(c.type, Numeric) and c.name not in _META
    ]


def _quarters(db: Session, model, security_id: int) -> list:
    """Quarterly rows, oldest→newest."""
    return list(
        db.scalars(
            select(model)
            .where(model.security_id == security_id, model.period == StatementPeriod.QUARTER)
            .order_by(model.fiscal_date.asc())
        )
    )


def build_ttm_for_security(db: Session, security_id: int) -> int:
    """Create/update TTM rows for one security from its quarterly statements."""
    dtos: list[StatementDTO] = []

    # Flows: rolling sum of the trailing 4 quarters.
    for stype, model in _FLOW_MODELS.items():
        cols = _numeric_columns(model)
        rows = _quarters(db, model, security_id)
        for i in range(3, len(rows)):
            window = rows[i - 3: i + 1]
            values: dict[str, float] = {}
            for col in cols:
                vals = [getattr(w, col) for w in window]
                present = [float(v) for v in vals if v is not None]
                if len(present) == 4:  # only a clean 4-quarter sum is a real TTM
                    values[col] = sum(present)
            if values:
                dtos.append(StatementDTO(
                    statement_type=stype,
                    fiscal_date=rows[i].fiscal_date,
                    period=StatementPeriod.TTM,
                    reported_currency=rows[i].reported_currency,
                    values=values,
                ))

    # Stocks: balance sheet is a snapshot — carry each quarter-end through as TTM.
    for stype, model in _STOCK_MODELS.items():
        cols = _numeric_columns(model)
        rows = _quarters(db, model, security_id)
        for r in rows:
            values = {c: float(getattr(r, c)) for c in cols if getattr(r, c) is not None}
            if values:
                dtos.append(StatementDTO(
                    statement_type=stype,
                    fiscal_date=r.fiscal_date,
                    period=StatementPeriod.TTM,
                    reported_currency=r.reported_currency,
                    values=values,
                ))

    return upsert_statements(db, security_id, dtos) if dtos else 0
