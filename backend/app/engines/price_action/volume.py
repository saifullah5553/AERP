"""Volume read against price, never on its own.

The rule the module enforces is the one people break first: volume confirms price, it does not
predict it. High volume is not bullish. Low volume is not bearish. What a volume number means
depends entirely on what price did on the same bar - which way it closed, how wide the range
was, and where in that range the close landed.

Everything here is arithmetic on raw volume: an average, a ratio to it, a comparison of two
windows. There is no OBV, no MFI, no money-flow construct - those turn the price-volume
relationship into a single line and hide exactly the disagreement worth seeing.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class VolumeRead:
    relative: float | None       # today's volume ÷ the recent average
    label: str                   # very_low | low | normal | high | very_high
    average: float | None
    note: str


# Ratio bands. Coarse on purpose: volume is noisy and a 1.9x day is not meaningfully different
# from a 2.1x day, so five buckets is as much resolution as the data supports.
_BANDS = ((0.5, "very_low"), (0.8, "low"), (1.5, "normal"), (2.5, "high"))


def average_volume(volume: list[float], window: int = 20, offset: int = 1) -> float | None:
    """Mean volume over the `window` sessions BEFORE the last `offset` bars.

    Excluding the current bar matters. Comparing today against an average that already contains
    today drags the yardstick toward whatever happened today, which is precisely the day you
    most want an independent reading of.
    """
    series = volume[:-offset] if offset else volume
    series = [v for v in series[-window:] if isinstance(v, int | float) and v > 0]
    if len(series) < max(3, window // 3):
        return None
    return sum(series) / len(series)


def relative_volume(volume: list[float], window: int = 20) -> VolumeRead:
    """Today's volume against its recent norm."""
    if not volume:
        return VolumeRead(None, "unknown", None, "no volume data")
    today = volume[-1]
    avg = average_volume(volume, window=window)
    if not avg or not isinstance(today, int | float) or today <= 0:
        return VolumeRead(None, "unknown", avg, "volume not reported for the latest session")
    ratio = today / avg
    label = "very_high"
    for cap, name in _BANDS:
        if ratio < cap:
            label = name
            break
    return VolumeRead(
        relative=round(ratio, 2), label=label, average=round(avg, 2),
        note=f"{today:,.0f} against a {window}-session average of {avg:,.0f} ({ratio:.2f}x)",
    )


def trend(volume: list[float], span: int = 5) -> str:
    """Is volume expanding or drying up across the last two windows?

    A drying-up pullback and an expanding selloff look identical on price alone, and they are
    opposite facts, so this comparison earns its place.
    """
    clean = [v for v in volume if isinstance(v, int | float) and v > 0]
    if len(clean) < span * 2:
        return "unknown"
    recent = sum(clean[-span:]) / span
    prior = sum(clean[-span * 2:-span]) / span
    if not prior:
        return "unknown"
    change = recent / prior
    if change >= 1.35:
        return "expanding"
    if change <= 0.7:
        return "drying_up"
    return "steady"


def price_volume_verdict(pct_change: float | None, vol: VolumeRead, *,
                         breakout: bool = False, breakdown: bool = False) -> str:
    """The price-and-volume pair read together, in words.

    This is the matrix from the brief, applied rather than recited: the same 3x volume day means
    demand behind a breakout, supply behind a breakdown, and absorption when price went nowhere.
    """
    if pct_change is None or vol.relative is None:
        return "volume cannot be judged without both a price move and a comparable average"
    strong_move = abs(pct_change) >= 2.0
    heavy = vol.relative >= 1.5
    light = vol.relative <= 0.8

    if breakout:
        if heavy:
            return "breakout on heavy volume - the move has buying behind it"
        if light:
            return "breakout on light volume - suspect until it is retested and holds"
        return "breakout on ordinary volume - not yet confirmed either way"
    if breakdown:
        if heavy:
            return "breakdown on heavy volume - real selling, not a shakeout"
        if light:
            return "breakdown on light volume - suspect; a quick recovery would make it a trap"
        return "breakdown on ordinary volume - unconfirmed"
    if strong_move and pct_change > 0:
        return ("strong advance on heavy volume - demand" if heavy else
                "strong advance on light volume - thin, easily given back")
    if strong_move and pct_change < 0:
        return ("sharp fall on heavy volume - supply" if heavy else
                "sharp fall on light volume - selling pressure looks limited")
    if heavy:
        return "price went nowhere on heavy volume - absorption; someone is taking the other side"
    if light:
        return "quiet session on light volume - ordinary consolidation"
    return "unremarkable price and volume"


def climax(close: list[float], high: list[float], low: list[float], volume: list[float],
           vol: VolumeRead) -> str | None:
    """A possible exhaustion bar - flagged, never asserted.

    Wants all three: extreme volume, a wide range, and a close rejected back into the bar. Even
    then it is only "possible", because a climax is confirmed by what happens NEXT and this
    function cannot see the future.
    """
    if vol.relative is None or vol.relative < 2.5 or len(close) < 2:
        return None
    bar_high, bar_low, bar_close = high[-1], low[-1], close[-1]
    span = bar_high - bar_low
    if span <= 0:
        return None
    close_position = (bar_close - bar_low) / span
    if close_position <= 0.35 and bar_high > max(high[-10:-1] or [bar_high]) * 0.995:
        return (f"possible buying climax: {vol.relative:.1f}x volume, wide range, closed in "
                "the bottom third after making a new high")
    if close_position >= 0.65 and bar_low < min(low[-10:-1] or [bar_low]) * 1.005:
        return (f"possible selling climax: {vol.relative:.1f}x volume, wide range, closed in "
                "the top third after making a new low")
    return None
