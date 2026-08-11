"""Divergence between price and an oscillator: RSI(14) and Elder's Force Index(13).

DELIBERATELY SEPARATE from engines/price_action. That package is indicator-free by instruction
and a test parses it to keep it that way; the technical SCORE is still built from structure,
levels and volume alone. What lives here is a screening FILTER - a different question, asked
with different tools - and keeping the two apart is what lets both instructions hold at once.
Nothing in this module feeds the technical score.

WHAT A DIVERGENCE IS, precisely, because the word is used loosely:

    BULLISH   price makes a LOWER low, the oscillator makes a HIGHER low
              - selling continues but with less force behind it
    BEARISH   price makes a HIGHER high, the oscillator makes a LOWER high
              - the advance continues but fewer buyers are carrying it

Both are measured at CONFIRMED SWING POINTS, not on every bar. A swing needs bars either side
of it to be a swing at all, so the newest few bars can never anchor one - which is correct, and
is why a divergence you can see the same day is usually imagination. The same pivot finder the
price-action engine uses is reused here so "a low" means the same thing in both places.

TWO GUARDS THAT KEEP THIS FROM FIRING CONSTANTLY. The two swings must be far enough apart in
time to be different events rather than one noisy turn, and the price move between them must be
big enough to be worth calling a lower low. Without those, any wobble qualifies and the filter
returns most of the market.
"""

from __future__ import annotations

from dataclasses import dataclass

# A divergence is between two SEPARATE turns. Closer than this and it is one event with a
# jagged middle.
MIN_BARS_APART = 5
MAX_BARS_APART = 60
# The price leg has to be a real move, not a rounding difference on two adjacent lows.
MIN_PRICE_MOVE = 0.02
MIN_BARS = 60
# The newer swing must be RECENT. Scanning a long window and accepting any qualifying pair
# returned 80% of the universe - almost every chart has a divergence somewhere in 120 bars, and
# one from four months ago that price has already resolved is history, not a setup. A trader
# asking for "stocks with a bearish RSI divergence" means the one on the chart NOW.
MAX_BARS_SINCE = 25


@dataclass(slots=True)
class Divergence:
    kind: str                 # bullish | bearish
    indicator: str            # rsi | efi
    from_date: str
    to_date: str
    price_from: float
    price_to: float
    value_from: float
    value_to: float
    bars_apart: int
    note: str


def rsi(close: list[float], period: int = 14) -> list[float | None]:
    """Wilder's RSI, as a series aligned to `close`.

    Wilder's smoothing rather than a simple average of gains and losses - the simple version is
    a different indicator that happens to share the name, and it turns at different places.
    """
    n = len(close)
    out: list[float | None] = [None] * n
    if n <= period:
        return out
    gains = losses = 0.0
    for i in range(1, period + 1):
        change = close[i] - close[i - 1]
        gains += max(change, 0.0)
        losses += max(-change, 0.0)
    avg_gain, avg_loss = gains / period, losses / period
    out[period] = 100.0 if avg_loss == 0 else 100.0 - 100.0 / (1 + avg_gain / avg_loss)
    for i in range(period + 1, n):
        change = close[i] - close[i - 1]
        avg_gain = (avg_gain * (period - 1) + max(change, 0.0)) / period
        avg_loss = (avg_loss * (period - 1) + max(-change, 0.0)) / period
        out[i] = 100.0 if avg_loss == 0 else 100.0 - 100.0 / (1 + avg_gain / avg_loss)
    return out


def force_index(close: list[float], volume: list[float], period: int = 13) -> list[float | None]:
    """Elder's Force Index: (close - previous close) x volume, EMA-smoothed.

    The raw one-day figure is far too noisy to read - Elder's own prescription is the 13-period
    EMA, and that is what "EFI" means in practice. Direction and the crossing of zero matter;
    the absolute number is in share-volume units and is not comparable between companies.
    """
    n = len(close)
    out: list[float | None] = [None] * n
    if n < period + 1:
        return out
    raw = [None] + [(close[i] - close[i - 1]) * (volume[i] or 0.0) for i in range(1, n)]
    seed = [v for v in raw[1:period + 1] if v is not None]
    if len(seed) < period:
        return out
    ema = sum(seed) / period
    out[period] = ema
    k = 2.0 / (period + 1)
    for i in range(period + 1, n):
        value = raw[i]
        if value is None:
            out[i] = ema
            continue
        ema = value * k + ema * (1 - k)
        out[i] = ema
    return out


def _at(series: list[float | None], idx: int) -> float | None:
    return series[idx] if 0 <= idx < len(series) and series[idx] is not None else None


def find(dates: list[str], high: list[float], low: list[float], close: list[float],
         volume: list[float], lookback: int = 120) -> list[Divergence]:
    """Every confirmed divergence in the recent window, newest pair last."""
    from app.engines.price_action.structure import swings

    if len(close) < MIN_BARS:
        return []
    start = max(0, len(close) - lookback)
    points = [s for s in swings(high, low, dates) if s.index >= start]
    if len(points) < 2:
        return []

    series = {"rsi": rsi(close), "efi": force_index(close, volume)}
    found: list[Divergence] = []

    for name, values in series.items():
        lows = [s for s in points if s.kind == "low"]
        highs = [s for s in points if s.kind == "high"]

        # Only the LAST TWO swings of each kind. Every consecutive pair in the window is how a
        # filter becomes a list of everything.
        # BULLISH: price lower low, indicator higher low.
        for older, newer in zip(lows[-2:], lows[-1:], strict=False):
            gap = newer.index - older.index
            if not MIN_BARS_APART <= gap <= MAX_BARS_APART:
                continue
            if len(close) - 1 - newer.index > MAX_BARS_SINCE:
                continue
            if newer.price >= older.price * (1 - MIN_PRICE_MOVE):
                continue
            a, b = _at(values, older.index), _at(values, newer.index)
            if a is None or b is None or b <= a:
                continue
            found.append(Divergence(
                "bullish", name, older.date, newer.date, older.price, newer.price, a, b, gap,
                f"price fell from {older.price:,.2f} to {newer.price:,.2f} while "
                f"{name.upper()} rose from {a:,.2f} to {b:,.2f}"))

        # BEARISH: price higher high, indicator lower high.
        for older, newer in zip(highs[-2:], highs[-1:], strict=False):
            gap = newer.index - older.index
            if not MIN_BARS_APART <= gap <= MAX_BARS_APART:
                continue
            if len(close) - 1 - newer.index > MAX_BARS_SINCE:
                continue
            if newer.price <= older.price * (1 + MIN_PRICE_MOVE):
                continue
            a, b = _at(values, older.index), _at(values, newer.index)
            if a is None or b is None or b >= a:
                continue
            found.append(Divergence(
                "bearish", name, older.date, newer.date, older.price, newer.price, a, b, gap,
                f"price rose from {older.price:,.2f} to {newer.price:,.2f} while "
                f"{name.upper()} fell from {a:,.2f} to {b:,.2f}"))

    found.sort(key=lambda d: d.to_date)
    return found


def summarise(dates, high, low, close, volume, lookback: int = 120) -> dict:
    """Flags for the screener row, plus the newest instance of each for the page.

    Only the MOST RECENT of each kind is kept. A company with four historical divergences is
    not four times the signal, and the one that matters is the one still in play.
    """
    out: dict = {
        "rsi_bullish": False, "rsi_bearish": False,
        "efi_bullish": False, "efi_bearish": False,
        "latest": None, "items": [],
    }
    try:
        found = find(list(dates), list(high), list(low), list(close), list(volume), lookback)
    except Exception:  # noqa: BLE001 - a filter must never break the daily refresh
        return out
    if not found:
        return out

    newest: dict[str, Divergence] = {}
    for d in found:
        newest[f"{d.indicator}_{d.kind}"] = d          # sorted by date, so last wins
    for key, d in newest.items():
        out[key] = True
        out["items"].append({
            "indicator": d.indicator, "kind": d.kind, "from_date": d.from_date,
            "to_date": d.to_date, "price_from": round(d.price_from, 4),
            "price_to": round(d.price_to, 4), "value_from": round(d.value_from, 4),
            "value_to": round(d.value_to, 4), "bars_apart": d.bars_apart, "note": d.note,
        })
    out["items"].sort(key=lambda x: x["to_date"], reverse=True)
    out["latest"] = out["items"][0]["to_date"] if out["items"] else None
    return out
