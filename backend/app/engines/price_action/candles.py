"""Candle reading: only formations that are unmistakable on the chart.

The discipline here is refusal. Most bars are ordinary and the honest answer is to say nothing
about them - a pattern detector that finds something every day is measuring its own thresholds,
not the market. Each test below carries explicit proportions, so "engulfing" means one body
genuinely swallowed the last one rather than merely closing a fraction beyond it.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class Bar:
    date: str
    open: float
    high: float
    low: float
    close: float
    volume: float | None = None

    @property
    def body(self) -> float:
        return abs(self.close - self.open)

    @property
    def span(self) -> float:
        return self.high - self.low

    @property
    def upper_wick(self) -> float:
        return self.high - max(self.open, self.close)

    @property
    def lower_wick(self) -> float:
        return min(self.open, self.close) - self.low

    @property
    def bullish(self) -> bool:
        return self.close > self.open

    @property
    def close_position(self) -> float | None:
        """Where in the bar's range the close landed: 1.0 on the high, 0.0 on the low."""
        return (self.close - self.low) / self.span if self.span > 0 else None


def to_bars(dates, open_, high, low, close, volume) -> list[Bar]:
    out: list[Bar] = []
    for i, day in enumerate(dates):
        try:
            o, h, low_, c = float(open_[i]), float(high[i]), float(low[i]), float(close[i])
        except (TypeError, ValueError, IndexError):
            continue
        if h <= 0 or low_ <= 0 or c <= 0 or h < low_:
            continue
        v = None
        try:
            v = float(volume[i]) if volume and volume[i] is not None else None
        except (TypeError, ValueError, IndexError):
            v = None
        out.append(Bar(str(day)[:10], o, h, low_, c, v))
    return out


def average_span(bars: list[Bar], window: int = 20) -> float | None:
    spans = [b.span for b in bars[-window - 1:-1] if b.span > 0]
    return sum(spans) / len(spans) if len(spans) >= 5 else None


def read(bars: list[Bar]) -> list[str]:
    """Named formations on the LAST bar, or an empty list when the bar is unremarkable."""
    if len(bars) < 2:
        return []
    last, prev = bars[-1], bars[-2]
    avg = average_span(bars)
    found: list[str] = []

    if last.span <= 0:
        return []

    # Rejection: a wick at least twice the body, with the close pushed well away from the extreme.
    if last.lower_wick >= last.body * 2 and (last.close_position or 0) >= 0.6:
        found.append("rejection of lower prices (long lower wick, closed near the high)")
    if last.upper_wick >= last.body * 2 and (last.close_position or 1) <= 0.4:
        found.append("rejection of higher prices (long upper wick, closed near the low)")

    # Engulfing: opposite colour AND the whole body covered, not just a marginal new close.
    if last.body > prev.body and prev.body > 0:
        if (last.bullish and not prev.bullish
                and last.close >= prev.open and last.open <= prev.close):
            found.append("bullish engulfing (took back the whole of the prior down bar)")
        if (not last.bullish and prev.bullish
                and last.close <= prev.open and last.open >= prev.close):
            found.append("bearish engulfing (gave back the whole of the prior up bar)")

    # Inside / outside bars describe the RELATIONSHIP, which is why they need the previous bar.
    if last.high <= prev.high and last.low >= prev.low:
        found.append("inside bar (contraction - the prior bar's range still governs)")
    elif last.high > prev.high and last.low < prev.low:
        found.append("outside bar (expansion - both sides of the prior range were traded)")

    # Wide-range expansion, measured against this instrument's own recent bars.
    if avg and last.span >= avg * 1.8:
        where = "closed near its high" if (last.close_position or 0) >= 0.7 else \
                "closed near its low" if (last.close_position or 1) <= 0.3 else "closed mid-range"
        found.append(f"wide-range expansion bar ({last.span / avg:.1f}x the recent range, {where})")

    # Indecision only counts when the range is also small - a doji on a huge bar is a fight,
    # not a shrug.
    if avg and last.body <= last.span * 0.2 and last.span <= avg * 0.8:
        found.append("narrow indecision bar (small body, below-average range)")

    return found


def quality(bars: list[Bar]) -> tuple[float, str]:
    """Score the last bar's price action out of 15, with the reason.

    Rewards decisiveness: a wide bar closing on its high is information, a narrow doji is not.
    Neither direction is favoured - a strong bearish close scores the same as a strong bullish
    one, because this measures the clarity of the action, not whether it suits a long.
    """
    if not bars:
        return 0.0, "no candle data"
    last = bars[-1]
    avg = average_span(bars)
    if last.span <= 0 or not avg:
        return 7.5, "not enough range history to judge the bar"

    pos = last.close_position or 0.5
    # Decisiveness of the close: 1.0 at either extreme, 0 dead in the middle.
    decisive = abs(pos - 0.5) * 2
    # Range conviction, capped so one freak bar cannot carry the score.
    conviction = min(last.span / avg, 2.0) / 2.0
    body_share = last.body / last.span

    score = 15.0 * (0.5 * decisive + 0.3 * conviction + 0.2 * body_share)
    where = "high" if pos >= 0.7 else "low" if pos <= 0.3 else "middle"
    return (round(min(score, 15.0), 2),
            f"closed near the {where} of a {last.span / avg:.1f}x range bar")
