"""The strategy signal: quality gate first, price-action timing second, then hold.

    BUY    - the business passes the quality gate AND price action says the move is starting
    HOLD   - already advancing and still fundamentally strong: stay in, don't churn
    WATCH  - quality business, but the timing isn't there yet (this is the shortlist)
    AVOID  - fails the fundamental gate; no technical setup can rescue it

The old engine flipped in and out on technical wobble, which the strategy backtest showed cost
money (median trade -1.86% against +5.69% for simply holding). Here the exit is fundamental:
a position is held while the business stays strong, exactly as intended for a positional trade
- SAZEW being held for years because the numbers kept improving, not because an oscillator said so.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np
from app.engines.strategy.entry import EntryResult, assess_entry
from app.engines.strategy.quality import QualityResult, assess_quality

BUY = "buy"
HOLD = "hold"
WATCH = "watch"
AVOID = "avoid"


@dataclass(slots=True)
class StrategySignal:
    action: str
    conviction: float | None                 # 0-100, blends business quality and timing
    quality: QualityResult | None = None
    entry: EntryResult | None = None
    rationale: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        q, e = self.quality, self.entry
        return {
            "action": self.action,
            "conviction": self.conviction,
            "quality_passed": q.passed if q else None,
            "quality_improving": q.improving if q else None,
            "quality_score": q.score if q else None,
            "quality_checks": q.checks if q else {},
            "quality_metrics": q.metrics if q else {},
            "entry_triggered": e.triggered if e else None,
            "entry_score": e.score if e else None,
            "entry_triggers": e.triggers if e else [],
            "entry_vetoes": e.vetoes if e else [],
            "rationale": self.rationale,
        }


def _in_uptrend(close: np.ndarray) -> bool:
    if len(close) < 200:
        return False
    px = float(close[-1])
    sma50 = float(close[-50:].mean())
    sma200 = float(close[-200:].mean())
    return px > sma50 > sma200


def evaluate(
    statements: dict[str, list[dict]],
    high: np.ndarray, low: np.ndarray, close: np.ndarray, volume: np.ndarray,
) -> StrategySignal:
    quality = assess_quality(statements)

    # Gate first: only businesses that are strong OR credibly improving earn a look at the
    # chart. No technical setup rescues a deteriorating business.
    if not quality.eligible:
        why = quality.reasons or ["insufficient_fundamentals"]
        return StrategySignal(
            action=AVOID, conviction=None, quality=quality, entry=None,
            rationale=[f"fails quality: {', '.join(why)}"],
        )

    entry = assess_entry(high, low, close, volume)
    qs = quality.score if quality.score is not None else 50.0
    es = entry.score if entry.score is not None else 0.0
    conviction = round(0.6 * qs + 0.4 * es, 2)
    grade = "strong" if quality.passed else "improving"

    if entry.triggered:
        return StrategySignal(
            action=BUY, conviction=conviction, quality=quality, entry=entry,
            rationale=[f"fundamentals {grade} ({qs:.0f})",
                       f"entry: {', '.join(entry.triggers)}"],
        )

    # Already advancing and still strong -> hold rather than re-enter or exit.
    if _in_uptrend(close):
        return StrategySignal(
            action=HOLD, conviction=conviction, quality=quality, entry=entry,
            rationale=[f"fundamentals {grade} and trending - hold"],
        )

    return StrategySignal(
        action=WATCH, conviction=conviction, quality=quality, entry=entry,
        rationale=[f"fundamentals {grade}, waiting for the move to start"]
        + ([f"blocked by: {', '.join(entry.vetoes)}"] if entry.vetoes else []),
    )
