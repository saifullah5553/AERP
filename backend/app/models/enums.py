"""Enumerations shared across models and schemas.

Stored as their string values in the database (native SQLAlchemy ``Enum``), which
keeps the data human-readable and avoids brittle integer mappings.
"""

from __future__ import annotations

import enum


class AssetClass(str, enum.Enum):
    EQUITY = "equity"
    CRYPTO = "crypto"
    FOREX = "forex"
    COMMODITY = "commodity"
    INDEX = "index"
    ETF = "etf"


class MarketRegion(str, enum.Enum):
    PSX = "psx"          # Pakistan Stock Exchange
    US = "us"            # NYSE / NASDAQ / AMEX
    INDIA = "india"      # NSE / BSE
    GCC = "gcc"          # Tadawul / DFM / ADX / etc.
    GLOBAL = "global"    # forex, commodities, crypto


class StatementPeriod(str, enum.Enum):
    ANNUAL = "annual"
    QUARTER = "quarter"
    TTM = "ttm"


class Timeframe(str, enum.Enum):
    D1 = "1d"
    H1 = "1h"
    M15 = "15m"
    M5 = "5m"
    M1 = "1m"


class SignalType(str, enum.Enum):
    STRONG_BUY = "strong_buy"
    BUY = "buy"
    HOLD = "hold"
    SELL = "sell"
    STRONG_SELL = "strong_sell"


class ScoreKind(str, enum.Enum):
    FUNDAMENTAL = "fundamental"
    TECHNICAL = "technical"
    MOMENTUM = "momentum"
    QUALITY = "quality"
    RISK = "risk"
    COMPOSITE = "composite"


class PatternDirection(str, enum.Enum):
    BULLISH = "bullish"
    BEARISH = "bearish"
    NEUTRAL = "neutral"


class PatternCategory(str, enum.Enum):
    CANDLESTICK = "candlestick"
    CHART = "chart"
    HARMONIC = "harmonic"
    WYCKOFF = "wyckoff"
    ELLIOTT = "elliott"


class CorporateActionType(str, enum.Enum):
    SPLIT = "split"
    REVERSE_SPLIT = "reverse_split"
    BONUS = "bonus"
    RIGHTS = "rights"
    MERGER = "merger"
    SPINOFF = "spinoff"


class InsiderTransactionType(str, enum.Enum):
    BUY = "buy"
    SELL = "sell"
    GRANT = "grant"
    EXERCISE = "exercise"
