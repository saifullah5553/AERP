"""Company-detail assembly service.

Gathers everything the company page needs from the database in one place. Every
piece is optional: if a security has no statements/scores/patterns yet, those
sections come back empty rather than fabricated.
"""

from __future__ import annotations

import enum
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.corporate import Dividend, InsiderTransaction
from app.models.enums import AssetClass, StatementPeriod
from app.models.fundamentals import (
    AnalystEstimate,
    BalanceSheet,
    CashFlowStatement,
    FinancialRatios,
    FundamentalSnapshot,
    IncomeStatement,
)
from app.models.market import Market, Security
from app.models.market_intel import NewsArticle
from app.models.quote import Quote
from app.models.scoring import Score, Signal
from app.models.technical import PatternDetection, TechnicalIndicator
from app.schemas.company import CompanyDetail, PeerOut, ScorePoint
from app.services.summary import build_summary

_SKIP_COLUMNS = {"created_at", "updated_at"}


def orm_to_dict(obj: Any) -> dict[str, Any]:
    """Serialise an ORM row to JSON-friendly primitives (Decimal→float, enum→value)."""
    out: dict[str, Any] = {}
    for col in obj.__table__.columns:
        if col.name in _SKIP_COLUMNS:
            continue
        value = getattr(obj, col.name)
        if isinstance(value, Decimal):
            value = float(value)
        elif isinstance(value, enum.Enum):
            value = value.value
        elif isinstance(value, date | datetime):
            value = value.isoformat()
        out[col.name] = value
    return out


def _tradingview_symbol(market_code: str, symbol: str, asset_class: AssetClass) -> str | None:
    if asset_class == AssetClass.CRYPTO:
        return f"BINANCE:{symbol}USDT"
    if asset_class == AssetClass.FOREX:
        return f"FX:{symbol}"
    if asset_class == AssetClass.COMMODITY:
        return {"GC": "TVC:GOLD", "SI": "TVC:SILVER", "CL": "TVC:USOIL"}.get(symbol)
    mapping = {
        "NASDAQ": f"NASDAQ:{symbol}",
        "NYSE": f"NYSE:{symbol}",
        "AMEX": f"AMEX:{symbol}",
        "NSE": f"NSE:{symbol}",
        "BSE": f"BSE:{symbol}",
        "TADAWUL": f"TADAWUL:{symbol}",
        "DFM": f"DFM:{symbol}",
        "ADX": f"ADX:{symbol}",
    }
    return mapping.get(market_code)  # PSX etc. → None (no reliable TV feed)


def _annual(db: Session, model, security_id: int, limit: int = 5) -> list[dict]:
    rows = db.scalars(
        select(model)
        .where(model.security_id == security_id, model.period == StatementPeriod.ANNUAL)
        .order_by(model.fiscal_date.desc())
        .limit(limit)
    ).all()
    return [orm_to_dict(r) for r in rows]


def _peers(db: Session, security: Security, limit: int = 8) -> list[PeerOut]:
    if not security.sector:
        return []
    latest_score = (
        select(Score.security_id, func.max(Score.as_of).label("as_of"))
        .group_by(Score.security_id)
        .subquery()
    )
    stmt = (
        select(
            Security.provider_symbol,
            Security.symbol,
            Security.name,
            Security.sector,
            Score.composite.label("composite"),
            Quote.price.label("price"),
        )
        .outerjoin(latest_score, latest_score.c.security_id == Security.id)
        .outerjoin(
            Score,
            (Score.security_id == Security.id) & (Score.as_of == latest_score.c.as_of),
        )
        .outerjoin(Quote, Quote.security_id == Security.id)
        .where(
            Security.sector == security.sector,
            Security.id != security.id,
            Security.is_active.is_(True),
        )
        .order_by(Score.composite.desc().nulls_last())
        .limit(limit)
    )
    peers: list[PeerOut] = []
    for r in db.execute(stmt).mappings():
        peers.append(
            PeerOut(
                provider_symbol=r["provider_symbol"],
                symbol=r["symbol"],
                name=r["name"],
                sector=r["sector"],
                composite_score=float(r["composite"]) if r["composite"] is not None else None,
                price=float(r["price"]) if r["price"] is not None else None,
            )
        )
    return peers


def get_company(db: Session, provider_symbol: str) -> CompanyDetail | None:
    security = db.scalar(
        select(Security).where(Security.provider_symbol == provider_symbol)
    )
    if security is None:
        return None
    market = db.get(Market, security.market_id)

    quote = db.get(Quote, security.id)
    latest_score = db.scalar(
        select(Score).where(Score.security_id == security.id).order_by(Score.as_of.desc())
    )
    latest_signal = db.scalar(
        select(Signal).where(Signal.security_id == security.id).order_by(Signal.as_of.desc())
    )
    snapshot = db.get(FundamentalSnapshot, security.id)
    ratios = db.scalar(
        select(FinancialRatios)
        .where(FinancialRatios.security_id == security.id)
        .order_by(FinancialRatios.fiscal_date.desc())
    )
    technical = db.scalar(
        select(TechnicalIndicator)
        .where(TechnicalIndicator.security_id == security.id)
        .order_by(TechnicalIndicator.date.desc())
    )
    patterns = db.scalars(
        select(PatternDetection)
        .where(PatternDetection.security_id == security.id, PatternDetection.is_active.is_(True))
        .order_by(PatternDetection.confidence.desc())
    ).all()
    history = db.scalars(
        select(Score)
        .where(Score.security_id == security.id)
        .order_by(Score.as_of.asc())
        .limit(180)
    ).all()
    dividends = db.scalars(
        select(Dividend)
        .where(Dividend.security_id == security.id)
        .order_by(Dividend.ex_date.desc())
        .limit(20)
    ).all()
    estimates = db.scalars(
        select(AnalystEstimate)
        .where(AnalystEstimate.security_id == security.id)
        .order_by(AnalystEstimate.fiscal_date.desc())
        .limit(8)
    ).all()
    news = db.scalars(
        select(NewsArticle)
        .where(NewsArticle.security_id == security.id)
        .order_by(NewsArticle.published_at.desc())
        .limit(10)
    ).all()
    insider = db.scalars(
        select(InsiderTransaction)
        .where(InsiderTransaction.security_id == security.id)
        .order_by(InsiderTransaction.transaction_date.desc())
        .limit(10)
    ).all()

    scores_dict = orm_to_dict(latest_score) if latest_score else None
    ratios_dict = orm_to_dict(ratios) if ratios else None
    signal_dict = orm_to_dict(latest_signal) if latest_signal else None
    top_pattern = patterns[0].name if patterns else None

    security_dict = orm_to_dict(security)
    security_dict["market_code"] = market.code if market else None
    security_dict["region"] = market.region.value if market else None

    return CompanyDetail(
        security=security_dict,
        tradingview_symbol=_tradingview_symbol(
            market.code if market else "", security.symbol, security.asset_class
        ),
        quote=orm_to_dict(quote) if quote else None,
        scores=scores_dict,
        signal=signal_dict,
        fundamentals=orm_to_dict(snapshot) if snapshot else None,
        ratios=ratios_dict,
        technical=orm_to_dict(technical) if technical else None,
        statements={
            "income": _annual(db, IncomeStatement, security.id),
            "balance": _annual(db, BalanceSheet, security.id),
            "cashflow": _annual(db, CashFlowStatement, security.id),
        },
        patterns=[orm_to_dict(p) for p in patterns],
        score_history=[
            ScorePoint(
                as_of=s.as_of,
                composite=float(s.composite) if s.composite is not None else None,
                fundamental=float(s.fundamental) if s.fundamental is not None else None,
                technical=float(s.technical) if s.technical is not None else None,
                momentum=float(s.momentum) if s.momentum is not None else None,
                quality=float(s.quality) if s.quality is not None else None,
                risk=float(s.risk) if s.risk is not None else None,
            )
            for s in history
        ],
        dividends=[orm_to_dict(d) for d in dividends],
        estimates=[orm_to_dict(e) for e in estimates],
        peers=_peers(db, security),
        news=[orm_to_dict(n) for n in news],
        insider=[orm_to_dict(i) for i in insider],
        ai_summary=build_summary(
            security.name or security.symbol, scores_dict, ratios_dict, signal_dict, top_pattern
        ),
    )
