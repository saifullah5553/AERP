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

    # ── Marubozu ─────────────────────────────────────────────
    if body >= 0.9 * rng:
        hits.append(PatternHit(
            "bullish_marubozu" if bull else "bearish_marubozu",
            CS, BULL if bull else BEAR, clamp01(body / rng), i,
        ))

    # ── Hammer / Hanging man ─────────────────────────────────
    if body > 0 and lower >= 2 * body and upper <= body:
        conf = clamp01(0.5 + (lower / (body + 1e-9) - 2) * 0.1)
        if downtrend:
            hits.append(PatternHit("hammer", CS, BULL, conf, i))
        else:
            hits.append(PatternHit("hanging_man", CS, BEAR, conf, i))

    # ── Shooting star / Inverted hammer ──────────────────────
    if body > 0 and upper >= 2 * body and lower <= body:
        conf = clamp01(0.5 + (upper / (body + 1e-9) - 2) * 0.1)
        if downtrend:
            hits.append(PatternHit("inverted_hammer", CS, BULL, conf, i))
        else:
            hits.append(PatternHit("shooting_star", CS, BEAR, conf, i))

    # ── Engulfing (2-bar) ────────────────────────────────────
    b1, _, _, _, bull1 = _metrics(o[i - 1], h[i - 1], low[i - 1], c[i - 1])
    engulf_conf = clamp01(0.6 + (body - b1) / rng)
    if not bull1 and bull and c[i] >= o[i - 1] and o[i] <= c[i - 1] and body > b1:
        hits.append(PatternHit("bullish_engulfing", CS, BULL, engulf_conf, i - 1))
    elif bull1 and not bull and c[i] <= o[i - 1] and o[i] >= c[i - 1] and body > b1:
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
    last3 = range(i - 2, i + 1)
    if all(c[j] > o[j] for j in last3) and c[i] > c[i - 1] > c[i - 2]:
        hits.append(PatternHit("three_white_soldiers", CS, BULL, 0.72, i - 2))
    elif all(c[j] < o[j] for j in last3) and c[i] < c[i - 1] < c[i - 2]:
        hits.append(PatternHit("three_black_crows", CS, BEAR, 0.72, i - 2))

    return hits
