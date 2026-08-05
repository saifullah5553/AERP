"""Candlestick-pattern detection on the most recent bars.

Each detector checks explicit geometric criteria on the latest formation and emits
a :class:`PatternHit` with a confidence scaled by how strongly the criteria hold.
Trend context (last-bar vs 10-bar mean) disambiguates look-alikes such as
hammer vs hanging man and shooting star vs inverted hammer.
"""

from __future__ import annotations

import numpy as np

from app.engines.patterns.base import PatternHit, clamp01
from app.models.enums import PatternCategory, PatternDirection

CS = PatternCategory.CANDLESTICK
BULL = PatternDirection.BULLISH
BEAR = PatternDirection.BEARISH
NEUTRAL = PatternDirection.NEUTRAL


def _metrics(o, h, low, c):
    body = abs(c - o)
    rng = max(h - low, 1e-9)
    upper = h - max(o, c)
    lower = min(o, c) - low
    return body, rng, upper, lower, c > o


def detect_candlesticks(
    o: np.ndarray, h: np.ndarray, low: np.ndarray, c: np.ndarray
) -> list[PatternHit]:
    n = len(c)
    if n < 3:
        return []
    hits: list[PatternHit] = []
    i = n - 1
    downtrend = c[i] < float(np.mean(c[-10:])) if n >= 10 else c[i] < c[i - 2]

    body, rng, upper, lower, bull = _metrics(o[i], h[i], low[i], c[i])

    # ── Doji ─────────────────────────────────────────────────
    if body <= 0.1 * rng:
        hits.append(PatternHit("doji", CS, NEUTRAL, clamp01(0.5 + (0.1 - body / rng) * 4), i))

    # ── Marubozu (full, opening, closing) ────────────────────
    # A full marubozu has no shadow at either end. The OPENING and CLOSING variants are
    # standard too and were previously missed: a bar that opens exactly at its high and then
    # sells off all day (open == high, lower shadow present) is a bearish opening marubozu -
    # a decisive rejection signal - even though its body is only ~75% of the range.
    if body >= 0.9 * rng:
        hits.append(PatternHit(
            "bullish_marubozu" if bull else "bearish_marubozu",
            CS, BULL if bull else BEAR, clamp01(body / rng), i,
        ))
    elif body >= 0.55 * rng:
        # Shadow at the open end vs the close end (differs by candle direction).
        open_shadow = upper if not bull else lower
        close_shadow = lower if not bull else upper
        flat = 0.05 * rng  # "no shadow" with a little tolerance for tick noise
        if open_shadow <= flat and close_shadow > flat:
            hits.append(PatternHit(
                "bullish_opening_marubozu" if bull else "bearish_opening_marubozu",
                CS, BULL if bull else BEAR, clamp01(body / rng), i,
            ))
        elif close_shadow <= flat and open_shadow > flat:
            hits.append(PatternHit(
                "bullish_closing_marubozu" if bull else "bearish_closing_marubozu",
                CS, BULL if bull else BEAR, clamp01(body / rng), i,
            ))

    # ── Hammer / Hanging man ─────────────────────────────────
    # The upper shadow is measured against the RANGE, not the body. A hammer is by definition
    # small-bodied, so "upper <= body" demanded a shadow of almost nothing and threw out
    # textbook hammers: a 0.2 body with a 7.0 lower shadow and a 0.3 upper wick was rejected
    # for being 0.1 too tall.
    if body > 0 and lower >= 2 * body and upper <= 0.15 * rng:
        conf = clamp01(0.5 + (lower / (body + 1e-9) - 2) * 0.1)
        if downtrend:
            hits.append(PatternHit("hammer", CS, BULL, conf, i))
        else:
            hits.append(PatternHit("hanging_man", CS, BEAR, conf, i))

    # ── Shooting star / Inverted hammer ──────────────────────
    # Mirror of the hammer, and it had the mirror of the same fault.
    if body > 0 and upper >= 2 * body and lower <= 0.15 * rng:
        conf = clamp01(0.5 + (upper / (body + 1e-9) - 2) * 0.1)
        if downtrend:
            hits.append(PatternHit("inverted_hammer", CS, BULL, conf, i))
        else:
            hits.append(PatternHit("shooting_star", CS, BEAR, conf, i))

    # ── Engulfing (2-bar) ────────────────────────────────────
    b1, rng1, _, _, bull1 = _metrics(o[i - 1], h[i - 1], low[i - 1], c[i - 1])
    engulf_conf = clamp01(0.6 + (body - b1) / rng)
    # The bar being engulfed must have a real body. Swallowing a doji is not a reversal - there
    # was no conviction to reverse - and it fired constantly on quiet days.
    real_first = b1 >= 0.3 * rng1
    if real_first and not bull1 and bull and c[i] >= o[i - 1] and o[i] <= c[i - 1] and body > b1:
        hits.append(PatternHit("bullish_engulfing", CS, BULL, engulf_conf, i - 1))
    elif (real_first and bull1 and not bull
          and c[i] <= o[i - 1] and o[i] >= c[i - 1] and body > b1):
        hits.append(PatternHit("bearish_engulfing", CS, BEAR, engulf_conf, i - 1))

    # ── Morning / Evening star (3-bar) ───────────────────────
    body3 = abs(c[i - 2] - o[i - 2])
    body2 = abs(c[i - 1] - o[i - 1])
    mid3 = (o[i - 2] + c[i - 2]) / 2
    avg_body = float(np.mean(np.abs(c[-10:] - o[-10:]))) if n >= 10 else body3
    if (
        c[i - 2] < o[i - 2] and body3 > avg_body * 0.8 and body2 < avg_body * 0.5
        and bull and c[i] > mid3
    ):
        hits.append(PatternHit("morning_star", CS, BULL, 0.7, i - 2))
    elif (
        c[i - 2] > o[i - 2] and body3 > avg_body * 0.8 and body2 < avg_body * 0.5
        and not bull and c[i] < mid3
    ):
        hits.append(PatternHit("evening_star", CS, BEAR, 0.7, i - 2))

    # ── Three white soldiers / black crows ───────────────────
    # Three LONG bodies, each closing near its high. Requiring only three rising closes made
    # this the loosest detector in the set - any three-day drift of a tenth of a percent
    # qualified, and on a quiet market it fired somewhere almost every day.
    last3 = range(i - 2, i + 1)
    bodies = [abs(c[j] - o[j]) for j in last3]
    ranges = [max(h[j] - low[j], 1e-9) for j in last3]
    substantial = all(b >= 0.6 * r for b, r in zip(bodies, ranges, strict=False)) and all(
        b >= avg_body * 0.8 for b in bodies)
    if (all(c[j] > o[j] for j in last3) and c[i] > c[i - 1] > c[i - 2] and substantial):
        hits.append(PatternHit("three_white_soldiers", CS, BULL, 0.72, i - 2))
    elif (all(c[j] < o[j] for j in last3) and c[i] < c[i - 1] < c[i - 2] and substantial):
        hits.append(PatternHit("three_black_crows", CS, BEAR, 0.72, i - 2))

    return hits
