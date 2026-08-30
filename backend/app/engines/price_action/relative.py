"""Relative strength: this security measured against its own market.

WHY THIS WAS THE GAP. The engine scored trend, levels, breakouts, volume and candles - five
readings, every one of them taken in isolation. A stock up 4% in a market up 9% scored exactly
the same as a stock up 4% in a market down 3%, and those are opposite facts. Relative strength
is the first thing a technician asks and the engine could not answer it.

It is also the one classical technique with the most durable evidence behind it, which matters
here: our own factor study found the previous technical inputs were NEGATIVE predictors over
60 days. Adding more of the same would compound that; adding the measure that is actually
supported is the point of the change.

DELIBERATELY NOT AN INDICATOR. This is a ratio of two closing prices and its slope - price
against price. Nothing is smoothed, nothing is oscillated, nothing has a period parameter
chosen to make a backtest look good. The package ban on named indicators stands, and the test
that enforces it is unaffected.

Two questions, because they are genuinely different:

    LEAD    is the security ahead of its market over the window?
    SLOPE   is that lead widening or narrowing right now?

A stock that outperformed six months ago and has been losing ground since is not strong, and a
single number that averages those two states describes neither.

HOW THE LEAD IS SCORED, AND WHY IT IS NOT A STRAIGHT LINE
---------------------------------------------------------
The first version of this scored the lead linearly - more lead, more points. Measuring it said
that was wrong. Panel study over our own pack, 477,047 point-in-time observations across all
six equity markets, 63-day lead against each security's own index, 60-day forward return:

    lead band        median forward return vs its own market
    below -30pp        -9.18%     <- far and away the worst
    -30 .. -13pp       -4.56%
    -13 ..  -8pp       -3.46%
     -8 ..  -4pp       -3.04%
     -4 ..  +5pp       -2.69%     <- the best zone is roughly IN LINE with the market
     +5 .. +12pp       -3.04%
    +12 .. +24pp       -3.38%
    above +24pp        -5.42%     <- the strongest names are the second worst

An inverted U, not a ramp. It survives clipping the extremes at 200/100/60pp, so it is the
shape of the data and not a handful of unadjusted splits. The overall rank IC is +0.038, and
almost all of that comes from the left tail: the honest description of this factor is "avoid
severe laggards", NOT "buy the strongest". Scoring it linearly would have handed a perfect 20
points to the +24pp-and-above bucket, which measured second-worst of the ten.

The score below therefore interpolates the MEASURED band returns onto 0-100. It is a
translation of that table, not a curve chosen because it backtested well.

WHAT THE SLOPE IS NOT USED FOR. The same study says a WIDENING lead underperforms a narrowing
one in all seven bands (-0.36 to -1.12pp, 466,606 observations) - the opposite of the +8-point
bonus this module originally gave it. A consistent sign across every band is worth reporting,
but half a point of forward return does not justify an eight-point swing in either direction on
one survivorship-biased sample. So the slope is described in the note and left out of the score.

READ THE CAVEATS. The pack holds today's universe, so anything delisted is absent and these
returns are survivorship-biased upward. The medians are negative throughout because the median
stock loses to its own cap-weighted index - only 41.3% of observations beat their market, while
the mean raw return is +5.52%. That is the usual skew, not a defect here. Nothing in this
module makes the composite signal validated; it is not.
"""

from __future__ import annotations

from dataclasses import dataclass

# About a quarter and about a month of trading days. Two windows rather than one because the
# question "is it ahead" and the question "is it still pulling ahead" need different lookbacks.
LONG_WINDOW = 63
SHORT_WINDOW = 21
MIN_BARS = 30


@dataclass(slots=True)
class RelativeRead:
    """None throughout when there is no benchmark to compare against - which is honest. A
    security whose market we cannot identify has no relative strength, and inventing one from
    its absolute move would just be the trend score again under another name."""

    lead_pct: float | None = None        # outperformance over LONG_WINDOW, percentage points
    recent_lead_pct: float | None = None  # same over SHORT_WINDOW
    improving: bool | None = None         # is the lead widening?
    score: float | None = None            # 0-100
    note: str = "no benchmark"


# (lead in percentage points, score) - the measured band table above, mapped onto 0-100 by
# linear scaling of its median forward return between the worst band (-9.18%) and the best
# (-2.69%). Anchors sit at each band's midpoint. Monotonic on neither side by construction:
# the peak is near zero because that is where the returns peaked.
_CURVE: tuple[tuple[float, float], ...] = (
    (-40.0, 0.0),    # below -30pp: -9.18%
    (-24.9, 71.2),   # -30..-13pp:  -4.56%
    (-16.3, 88.1),   # -13..-8pp:   -3.46%
    (-10.7, 94.6),   # -8..-4pp:    -3.04%
    (-6.3, 100.0),   # the peak
    (-2.1, 98.3),
    (2.6, 97.2),
    (8.4, 94.6),     # +5..+12pp:   -3.04%
    (18.1, 89.4),    # +12..+24pp:  -3.38%
    (45.0, 57.9),    # above +24pp: -5.42%
)


def _score_lead(lead: float) -> float:
    """Interpolate the measured curve. Flat outside the ends rather than extrapolated - we have
    no evidence about a -200pp lead, and inventing a trend there would be the exact mistake the
    linear version made at the top end."""
    if lead <= _CURVE[0][0]:
        return _CURVE[0][1]
    if lead >= _CURVE[-1][0]:
        return _CURVE[-1][1]
    for (x0, y0), (x1, y1) in zip(_CURVE, _CURVE[1:], strict=False):
        if x0 <= lead <= x1:
            span = x1 - x0
            return y0 if span == 0 else y0 + (y1 - y0) * (lead - x0) / span
    return 50.0


def _pct_change(series: list[float], window: int) -> float | None:
    if len(series) <= window:
        return None
    start, end = series[-1 - window], series[-1]
    if start is None or end is None or start <= 0:
        return None
    return (end / start - 1.0) * 100.0


def _clean(bars: list) -> list[float]:
    """Closes only, gaps dropped. A missing close is skipped rather than carried forward:
    holding yesterday's price over a gap invents a flat day that never traded."""
    out: list[float] = []
    for b in bars:
        close = getattr(b, "close", None)
        if close is None and isinstance(b, dict):
            close = b.get("close")
        try:
            value = float(close)
        except (TypeError, ValueError):
            continue
        if value > 0:
            out.append(value)
    return out


def read(bars: list, benchmark_bars: list | None) -> RelativeRead:
    """Compare the security's move with its market's over the same windows.

    Both series are trimmed to the same length from the RIGHT, so the comparison covers the
    same recent period even when one series starts earlier or carries a different number of
    holidays. Aligning from the left would measure two different stretches of calendar and call
    the difference relative strength.
    """
    if not benchmark_bars:
        return RelativeRead()

    stock = _clean(bars)
    index = _clean(benchmark_bars)
    n = min(len(stock), len(index))
    if n < MIN_BARS:
        return RelativeRead(note="not enough overlapping history")
    stock, index = stock[-n:], index[-n:]

    long_window = min(LONG_WINDOW, n - 1)
    short_window = min(SHORT_WINDOW, n - 1)

    s_long, i_long = _pct_change(stock, long_window), _pct_change(index, long_window)
    s_short, i_short = _pct_change(stock, short_window), _pct_change(index, short_window)
    if s_long is None or i_long is None:
        return RelativeRead(note="not enough overlapping history")

    lead = s_long - i_long
    recent = (s_short - i_short) if (s_short is not None and i_short is not None) else None

    # The short window is a SUBSET of the long one, so comparing their per-day rates - not
    # their totals - is what says whether the lead is widening. Comparing a 21-day total with
    # a 63-day total would call almost every steady outperformer "deteriorating".
    improving = None
    if recent is not None and short_window > 0 and long_window > 0:
        improving = (recent / short_window) > (lead / long_window)

    base = _score_lead(lead)

    if lead > 2:
        note = f"leading its market by {lead:.1f}pp over {long_window} days"
    elif lead < -2:
        note = f"lagging its market by {abs(lead):.1f}pp over {long_window} days"
    else:
        note = f"tracking its market ({lead:+.1f}pp over {long_window} days)"
    # Reported, deliberately not scored - see the module docstring. Worded so it does not imply
    # a widening lead is the better state, because measured over 466,606 observations it isn't.
    if improving is True:
        note += "; the lead is widening"
    elif improving is False:
        note += "; the lead is narrowing"

    return RelativeRead(
        lead_pct=round(lead, 2),
        recent_lead_pct=None if recent is None else round(recent, 2),
        improving=improving,
        score=round(base, 1),
        note=note,
    )
