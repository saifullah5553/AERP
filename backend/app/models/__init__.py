"""Model registry.

Importing this package imports every model so that ``Base.metadata`` is fully
populated — required for Alembic autogeneration and ``create_all``.
"""

from app.models.base import Base, TimestampMixin
from app.models.corporate import (
    CorporateAction,
    Dividend,
    InsiderSummary,
    InsiderTransaction,
)
from app.models.fundamentals import (
    AnalystEstimate,
    BalanceSheet,
    CashFlowStatement,
    FinancialRatios,
    FundamentalSnapshot,
    IncomeStatement,
)
from app.models.macro import MacroIndicator
from app.models.market import Market, Security
from app.models.market_intel import EconomicEvent, NewsArticle
from app.models.prices import DailyPrice, IntradayPrice
from app.models.quote import Quote
from app.models.scoring import Score, Signal
from app.models.technical import PatternDetection, TechnicalIndicator
from app.models.user import (
    Portfolio,
    PortfolioPosition,
    User,
    Watchlist,
    WatchlistItem,
)

__all__ = [
    "Base",
    "TimestampMixin",
    "Market",
    "Security",
    "DailyPrice",
    "IntradayPrice",
    "Quote",
    "IncomeStatement",
    "BalanceSheet",
    "CashFlowStatement",
    "FinancialRatios",
    "FundamentalSnapshot",
    "AnalystEstimate",
    "TechnicalIndicator",
    "PatternDetection",
    "CorporateAction",
    "Dividend",
    "InsiderTransaction",
    "InsiderSummary",
    "NewsArticle",
    "EconomicEvent",
    "MacroIndicator",
    "Score",
    "Signal",
    "User",
    "Watchlist",
    "WatchlistItem",
    "Portfolio",
    "PortfolioPosition",
]
