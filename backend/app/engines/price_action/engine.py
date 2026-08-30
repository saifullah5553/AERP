"""Price action + volume technical engine.

Replaces the indicator engine entirely. There is no RSI, MACD, moving average, ATR, ADX,
Bollinger band, VWAP, OBV, MFI, Supertrend, Ichimoku or oscillator of any kind in this package -
not renamed, not internal, not "just for smoothing". The only inputs are OHLC and volume, and
the only derived numbers are measurements a person could take off the chart with a ruler:
percentage moves, ranges, averages of volume, counts of touches, distances to levels.

    Structure          25   where the swings are, and whether they are rising or falling
    Support/resistance 20   how close price is to a level, and how well tested that level is
    Breakout quality   20   did it CLOSE through, on what volume, and did it hold
    Relative strength  20   is it beating its own market, and is that lead widening
    Volume confirmation 15  volume read against the price move it accompanied
                       ---
                       100

Candle reading was removed from the SCORE on 2026-08-30. It carried 15 points on the shape of
a single bar, the detectors had measured defects (three_black_crows fired on 10% of all bars),
and our own factor study found the technical inputs were negative predictors over 60 days.
Relative strength took the weight because it is the measure a technician reaches for first and
the one thing this engine could not previously say: a stock up 4% in a market up 9% and a stock
up 4% in a market down 3% scored identically, and those are opposite facts. The candle notes
are still computed and still reported - they just no longer move the number.

The score is a summary of those five readings, not a prediction, and it deliberately cannot be
moved by anything fundamental - no earnings, no valuation, no news, no analyst view.

Two refusals are built in. A setup is only returned when the structure actually offers one, and
`NO TRADE - WAIT` is a first-class answer rather than a failure. And a breakout is never called
confirmed on the strength of price alone: it needs a close through the level and volume behind
it, or it is reported as forming, suspect, or failed.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from app.engines.price_action import candles as C
from app.engines.price_action import relative as R
from app.engines.price_action import structure as S
from app.engines.price_action import volume as V

# Weekly structure needs roughly a year of weeks to say anything; daily structure needs enough
# bars for swings to confirm. Below this the honest output is "cannot be determined".
MIN_BARS = 40


@dataclass(slots=True)
class Setup:
    kind: str
    aggressive_entry: float | None = None
    conservative_entry: float | None = None
    stop: float | None = None
    target_1: float | None = None
    target_2: float | None = None
    major_target: float | None = None
    risk_reward: float | None = None
    rationale: str = ""


@dataclass(slots=True)
class PriceActionResult:
    score: float | None
    bias: str                     # bullish | neutral | bearish
    phase: str                    # accumulation | markup | distribution | markdown | range
    phase_confidence: str         # low | medium | high
    structure_daily: str
    structure_weekly: str
    breakout_status: str
    setup: Setup
    components: dict[str, float] = field(default_factory=dict)
    zones: list[dict] = field(default_factory=list)
    volume: dict[str, Any] = field(default_factory=dict)
    candle_notes: list[str] = field(default_factory=list)
    relative: dict[str, Any] = field(default_factory=dict)
    summary: str = ""
    what_changes_it: dict[str, str] = field(default_factory=dict)
    quality: str = "unrated"      # excellent | good | average | weak | avoid
    notes: list[str] = field(default_factory=list)


def to_weekly(bars: list[C.Bar]) -> list[C.Bar]:
    """Aggregate daily bars into weeks by ISO week, so weekly structure is read on real weeks."""
    if not bars:
        return []
    buckets: dict[str, list[C.Bar]] = {}
    for b in bars:
        try:
            year, week, _ = _iso(b.date)
        except ValueError:
            continue
        buckets.setdefault(f"{year}-W{week:02d}", []).append(b)
    weekly: list[C.Bar] = []
    for key in sorted(buckets):
        group = buckets[key]
        vols = [g.volume for g in group if g.volume is not None]
        weekly.append(C.Bar(
            date=group[-1].date, open=group[0].open,
            high=max(g.high for g in group), low=min(g.low for g in group),
            close=group[-1].close, volume=sum(vols) if vols else None,
        ))
    return weekly


def _iso(day: str) -> tuple[int, int, int]:
    from datetime import date

    return date(int(day[:4]), int(day[5:7]), int(day[8:10])).isocalendar()


def _breakout(bars: list[C.Bar], zones: list[S.Zone], vol: V.VolumeRead,
              lookback: int = 10) -> tuple[str, float, str]:
    """Breakout / breakdown status, its share of the 20 points, and the evidence.

    A move through a level is not a breakout. The test is a CLOSE through it, and then what
    happened afterwards - held, retested and held, or came straight back. Price merely trading
    beyond a level intraday is the single most common false positive on any chart.
    """
    if not bars or not zones:
        return "no_breakout", 10.0, "no tested level nearby to break"

    last = bars[-1]
    price = last.close
    recent = bars[-lookback:]
    # A break has to CLEAR the level, not graze it. Without a margin, price oscillating around
    # a zone edge - which is what price does at a level, by definition - registered as a break
    # and then a failure of it: 54% of the universe came back flagged as a failed break and
    # 2,478 names were handed a "bear trap" setup. A quarter of the market is not a bear trap.
    # The margin is proportional so it means the same thing on a 5 rupee share and a 500 one.
    margin = 0.015

    res = [z for z in zones if z.kind == "resistance"]
    sup = [z for z in zones if z.kind == "support"]

    # A level is "broken" when the latest close is beyond it but recent bars traded below/above,
    # i.e. the break happened inside the window we can still see the consequences of.
    for zone in sorted(res, key=lambda z: -z.mid):
        if price > zone.high * (1 + margin) and any(b.close <= zone.high
                                                     for b in recent[:-1]):
            through = (price / zone.high - 1) * 100
            after = [b for b in recent if b.close > zone.high]
            held = len(after) >= 2
            retested = any(b.low <= zone.high * 1.005 for b in after) and held
            if vol.relative is not None and vol.relative >= 1.5 and retested:
                return ("breakout_retest_held", 20.0,
                        f"closed {through:.1f}% above the {zone.low:,.2f}-{zone.high:,.2f} zone "
                        f"on {vol.relative:.1f}x volume, came back to it and held")
            if vol.relative is not None and vol.relative >= 1.5:
                return ("confirmed_breakout", 17.0,
                        f"closed {through:.1f}% above {zone.high:,.2f} "
                        f"on {vol.relative:.1f}x volume")
            if vol.relative is not None and vol.relative <= 0.8:
                return ("breakout_suspect_low_volume", 9.0,
                        f"closed above {zone.high:,.2f} but on {vol.relative:.1f}x volume - "
                        "no weight behind it")
            return ("breakout_forming", 13.0,
                    f"closed {through:.1f}% above {zone.high:,.2f} on ordinary volume")

    for zone in sorted(sup, key=lambda z: z.mid):
        if price < zone.low * (1 - margin) and any(b.close >= zone.low
                                                   for b in recent[:-1]):
            through = (1 - price / zone.low) * 100
            if vol.relative is not None and vol.relative >= 1.5:
                return ("confirmed_breakdown", 3.0,
                        f"closed {through:.1f}% below {zone.low:,.2f} on {vol.relative:.1f}x "
                        "volume - real selling")
            return ("breakdown_forming", 6.0,
                    f"closed below {zone.low:,.2f} on unremarkable volume - unconfirmed")

    # FAILURES are checked against every zone, whatever it is currently labelled, and require a
    # full round trip ACROSS the band. Splitting by label made these near-tautological: a zone
    # is called resistance precisely because it sits above price, so "price is below the
    # resistance it broke" was true by construction and 26% of the universe came back as a
    # failed breakout. Price must have closed clear of one side and then closed clear of the
    # other - which is what a trap actually looks like, and is genuinely uncommon.
    for zone in zones:
        cleared_above = [b for b in recent[:-1] if b.close > zone.high * (1 + margin)]
        cleared_below = [b for b in recent[:-1] if b.close < zone.low * (1 - margin)]
        if cleared_above and price < zone.low * (1 - margin):
            return ("failed_breakout", 4.0,
                    f"closed clear above {zone.high:,.2f} and is now back below "
                    f"{zone.low:,.2f} - a trap unless it is reclaimed")
        if cleared_below and price > zone.high * (1 + margin):
            return ("failed_breakdown", 16.0,
                    f"lost {zone.low:,.2f} on a closing basis and has reclaimed "
                    f"{zone.high:,.2f} - a bear trap, which is a bullish tell")

    return "no_breakout", 10.0, "price is inside its range; no level has been broken"


def _phase(struct: S.Structure, vol_trend: str, breakout: str,
           in_range: bool) -> tuple[str, str, str]:
    """Accumulation / markup / distribution / markdown / range, with the evidence and a hedge.

    Never asserts institutional intent. The most this can honestly say is that the price and
    volume behaviour is CONSISTENT WITH accumulation - the participants are not visible in
    OHLCV and claiming otherwise is storytelling.
    """
    label = struct.label
    if label in ("strong_uptrend", "weak_uptrend") and not in_range:
        return "markup", "medium", "higher highs and higher lows with price out of its range"
    if label in ("strong_downtrend", "weak_downtrend") and not in_range:
        return "markdown", "medium", "lower highs and lower lows"
    if label == "downtrend_to_accumulation" or (in_range and vol_trend == "drying_up"):
        conf = "medium" if breakout in ("breakout_forming", "confirmed_breakout") else "low"
        return ("accumulation", conf,
                "price ranging with volume drying up on the down moves - consistent with "
                "accumulation, though the buyers themselves are not visible in this data")
    if label == "uptrend_to_distribution" or (in_range and vol_trend == "expanding"):
        return ("distribution", "low",
                "heavy volume without upward progress after an advance - consistent with "
                "distribution rather than proof of it")
    return "range", "low", "no directional structure; price is rotating inside a band"


def _setup(bars: list[C.Bar], zones: list[S.Zone], struct: S.Structure, breakout: str,
           vol: V.VolumeRead) -> Setup:
    """A trade only where the structure offers one. Otherwise NO TRADE - WAIT."""
    if not bars:
        return Setup("no_trade", rationale="no price data")
    price = bars[-1].close
    support = S.nearest(zones, price, "support")
    resistance = S.nearest(zones, price, "resistance")

    bullish_break = breakout in ("confirmed_breakout", "breakout_retest_held", "breakout_forming")
    bounce = (struct.label in ("strong_uptrend", "weak_uptrend") and support is not None
              and price <= support.high * 1.06)

    if bullish_break and support is not None:
        stop = round(support.low * 0.99, 4)
        t1 = round(resistance.low, 4) if resistance else round(price * 1.08, 4)
        t2 = round(t1 * 1.06, 4)
        risk, reward = price - stop, t1 - price
        return Setup(
            kind="breakout continuation" if breakout != "breakout_retest_held"
            else "breakout + successful retest",
            aggressive_entry=round(price, 4),
            conservative_entry=round(max(support.high, price * 0.985), 4),
            stop=stop, target_1=t1, target_2=t2,
            major_target=round(t2 * 1.10, 4),
            risk_reward=round(reward / risk, 2) if risk > 0 and reward > 0 else None,
            rationale=(f"broke the level and held; invalid below {stop:,.2f}, which would put "
                       "price back inside the range it just left"),
        )
    if bounce and support is not None:
        stop = round(support.low * 0.985, 4)
        t1 = round(resistance.low, 4) if resistance else round(price * 1.07, 4)
        risk, reward = price - stop, t1 - price
        return Setup(
            kind="pullback into support within an uptrend",
            aggressive_entry=round(price, 4),
            conservative_entry=round(support.high, 4),
            stop=stop, target_1=t1, target_2=round(t1 * 1.05, 4),
            major_target=round(t1 * 1.12, 4),
            risk_reward=round(reward / risk, 2) if risk > 0 and reward > 0 else None,
            rationale=(f"higher-low structure with support at {support.low:,.2f}-"
                       f"{support.high:,.2f}; a close below breaks that structure"),
        )
    if breakout == "failed_breakdown" and support is not None:
        stop = round(min(b.low for b in bars[-10:]) * 0.99, 4)
        t1 = round(resistance.low, 4) if resistance else round(price * 1.08, 4)
        risk, reward = price - stop, t1 - price
        return Setup(
            kind="failed breakdown / bear trap",
            aggressive_entry=round(price, 4), conservative_entry=round(price * 0.99, 4),
            stop=stop, target_1=t1, target_2=round(t1 * 1.06, 4),
            major_target=round(t1 * 1.12, 4),
            risk_reward=round(reward / risk, 2) if risk > 0 and reward > 0 else None,
            rationale="support was lost intraday and reclaimed on the close; invalid on a "
                      "second, decisive loss of the same level",
        )

    waiting = "a close above the nearest resistance zone on above-average volume"
    if resistance:
        waiting = (f"a close above {resistance.high:,.2f} on volume clearly above its "
                   f"{vol.average:,.0f} average" if vol.average else
                   f"a close above {resistance.high:,.2f} on heavy volume")
    return Setup("no_trade", rationale=f"NO TRADE - WAIT. Trigger: {waiting}.")


# The chart legs' natural maxima (structure 25, levels 20, breakout 20, volume 20) and the
# share of the score they carry. Relative strength takes the remaining 10 - see the note at
# its call site for the measurement that sized it.
CORE_MAX = 85.0
CORE_TARGET = 90.0
RELATIVE_MAX = 10.0


def _structure_points(struct: S.Structure) -> float:
    return {
        "strong_uptrend": 25.0, "weak_uptrend": 19.0,
        "downtrend_to_accumulation": 17.0, "range": 12.5,
        "uptrend_to_distribution": 8.0, "weak_downtrend": 6.0,
        "strong_downtrend": 2.0, "insufficient_history": 10.0,
    }.get(struct.label, 12.5)


def _level_points(zones: list[S.Zone], price: float) -> tuple[float, str]:
    """Room to the next resistance, and how well the support underneath is tested."""
    support = S.nearest(zones, price, "support")
    resistance = S.nearest(zones, price, "resistance")
    if not support and not resistance:
        return 10.0, "no well-tested level either side"
    points, bits = 0.0, []
    if support:
        # Close to well-tested support is the good case: the risk is defined and small.
        distance = (price / support.high - 1) * 100 if support.high else 99
        near = max(0.0, 1 - min(distance, 15) / 15)
        points += 6.0 * near + (4.0 if support.strength == "major" else 2.0)
        bits.append(f"support {support.low:,.2f}-{support.high:,.2f} ({support.touches} tests)")
    if resistance:
        room = (resistance.low / price - 1) * 100 if price else 0
        points += min(room / 12, 1.0) * 10.0
        bits.append(f"resistance {resistance.low:,.2f}-{resistance.high:,.2f} "
                    f"({room:.1f}% away)")
    else:
        # Nothing overhead. A stock at all-time highs has no tested resistance by definition,
        # and treating that absence as "no data" scored Apple 38/100 while it was making new
        # highs. Clear road above is the most bullish thing this section can report, not a gap
        # in it.
        points += 10.0
        bits.append("no tested resistance overhead - price is in clear air")
    return round(min(points, 20.0), 2), "; ".join(bits)


def _volume_points(vol: V.VolumeRead, vol_trend: str, breakout: str) -> float:
    if vol.relative is None:
        return 10.0
    if breakout in ("confirmed_breakout", "breakout_retest_held"):
        return 20.0 if vol.relative >= 2.0 else 17.0
    if breakout in ("confirmed_breakdown",):
        return 2.0
    if breakout == "breakout_suspect_low_volume":
        return 7.0
    if vol_trend == "drying_up":
        return 14.0     # quiet pullback: constructive, not conclusive
    if vol_trend == "expanding":
        return 13.0
    return 11.0


def analyse(dates, open_, high, low, close, volume,
            benchmark_bars: list | None = None) -> PriceActionResult:
    """The whole read, from OHLCV alone."""
    bars = C.to_bars(dates, open_, high, low, close, volume)
    if len(bars) < MIN_BARS:
        return PriceActionResult(
            score=None, bias="neutral", phase="unknown", phase_confidence="low",
            structure_daily="insufficient_history", structure_weekly="insufficient_history",
            breakout_status="unknown", setup=Setup("no_trade", rationale="NO TRADE - WAIT."),
            summary=f"only {len(bars)} usable sessions; structure cannot be determined",
            notes=[f"needs at least {MIN_BARS} sessions of OHLCV"],
        )

    price = bars[-1].close
    vols = [b.volume if b.volume is not None else 0.0 for b in bars]
    highs = [b.high for b in bars]
    lows = [b.low for b in bars]
    closes = [b.close for b in bars]
    days = [b.date for b in bars]

    daily_swings = S.swings(highs, lows, days)
    daily_struct = S.classify_structure(daily_swings, closes)
    weekly = to_weekly(bars)
    weekly_struct = S.classify_structure(
        S.swings([b.high for b in weekly], [b.low for b in weekly], [b.date for b in weekly],
                 left=2, right=2),
        [b.close for b in weekly]) if len(weekly) >= 12 else S.Structure("insufficient_history")

    level_zones = S.zones(daily_swings, closes, highs, lows, price)
    vol = V.relative_volume(vols)
    vol_trend = V.trend(vols)
    status, breakout_points, breakout_note = _breakout(bars, level_zones, vol)

    pct = ((price / bars[-2].close - 1) * 100) if len(bars) > 1 and bars[-2].close else None
    verdict = V.price_volume_verdict(
        pct, vol,
        breakout=status.startswith("breakout") or status == "confirmed_breakout",
        breakdown=status.startswith("breakdown") or status == "confirmed_breakdown")
    climax_note = V.climax(closes, highs, lows, vols, vol)

    # "In range" means the last stretch has gone nowhere - the precondition for calling a phase
    # accumulation or distribution rather than trend.
    window = closes[-30:]
    in_range = bool(window) and (max(window) / min(window) - 1) < 0.18
    phase, confidence, phase_note = _phase(daily_struct, vol_trend, status, in_range)

    candle_notes = C.read(bars)
    struct_points = _structure_points(daily_struct)
    level_points, level_note = _level_points(level_zones, price)
    volume_points = _volume_points(vol, vol_trend, status)

    # RELATIVE STRENGTH replaces the candle score. A single bar's shape carried 15 points and
    # earned none of them: the detectors had real defects (three_black_crows fired on 10% of
    # all bars), and the factor study found the technical inputs were negative predictors over
    # 60 days. Whether a security is beating its own market is the measure a technician reaches
    # for first, and it was the one thing this engine could not say.
    #
    # IT CARRIES 10 POINTS, NOT 20, AND THE MEASUREMENT IS WHY. Scored on the curve its own
    # panel study produced, 62% of today's 9,760 securities land between 88 and 100 and only
    # 11% fall below 50: the factor genuinely separates severe laggards and genuinely cannot
    # tell the rest apart. Handing a near-constant leg a fifth of the score would not add
    # information, it would DILUTE the four legs that do discriminate - the same number of
    # points, a smaller share of them doing any work. So it is sized as what it measured as:
    # a penalty on the weak tail, costing a severe laggard its full 10 and a typical name
    # under one.
    rel = R.read(bars, benchmark_bars)
    rel_points = 0.0 if rel.score is None else rel.score / 100.0 * RELATIVE_MAX

    # Candle reading is still COMPUTED and still reported in `candle_notes` for anyone reading
    # one chart; it simply no longer moves the number.
    #
    # The four chart legs top out at 25 + 20 + 20 + 20 = 85 by the natural scales of the
    # functions above, and relative strength adds 10. Scale them to 90 so a perfect read is
    # exactly 100 - without this the score silently capped at 95 and nothing said so.
    core_lift = CORE_TARGET / CORE_MAX
    struct_points *= core_lift
    level_points *= core_lift
    breakout_points *= core_lift
    volume_points *= core_lift

    if rel.score is None:
        # No benchmark: renormalise over what WAS measurable, rather than scoring a zero for
        # the missing leg and marking down every security whose index we cannot resolve.
        #
        # Scale the components themselves, not just the total. The published invariant is that
        # the parts sum to the score - that is what makes it auditable, and a total quietly
        # larger than its own breakdown would be exactly the kind of number this project keeps
        # having to un-trust.
        lift = 100.0 / CORE_TARGET
        struct_points *= lift
        level_points *= lift
        breakout_points *= lift
        volume_points *= lift
    # Round the parts FIRST and total the rounded parts, so the breakdown adds up to the
    # published score exactly rather than to within a rounding error. `levels` used to be
    # stored unrounded while the rest were rounded, which left the four components on a company
    # page summing to 48.22 beside a score of 48.24 - small, but the page then disagrees with
    # itself and there is no way for a reader to tell that apart from a real fault.
    parts = {
        "structure": round(struct_points, 2),
        "levels": round(level_points, 2),
        "breakout": round(breakout_points, 2),
        "volume": round(volume_points, 2),
        "relative_strength": round(rel_points, 2),
    }
    total = round(sum(parts.values()), 2)
    setup = _setup(bars, level_zones, daily_struct, status, vol)

    bias = ("bullish" if total >= 62 and daily_struct.label not in
            ("strong_downtrend", "weak_downtrend")
            else "bearish" if total <= 40 or daily_struct.label == "strong_downtrend"
            else "neutral")
    quality = ("excellent" if total >= 80 else "good" if total >= 68 else
               "average" if total >= 52 else "weak" if total >= 38 else "avoid")

    notes = [n for n in (climax_note,) if n]
    resistance = S.nearest(level_zones, price, "resistance")
    support = S.nearest(level_zones, price, "support")
    return PriceActionResult(
        score=total, bias=bias, phase=phase, phase_confidence=confidence,
        structure_daily=daily_struct.label, structure_weekly=weekly_struct.label,
        breakout_status=status, setup=setup,
        components={
            **parts,
        },
        relative={"lead_pct": rel.lead_pct, "recent_lead_pct": rel.recent_lead_pct,
                  "improving": rel.improving, "score": rel.score, "note": rel.note},
        zones=[asdict(z) for z in level_zones],
        volume={"relative": vol.relative, "label": vol.label, "average": vol.average,
                "trend": vol_trend, "note": vol.note, "verdict": verdict},
        candle_notes=candle_notes,
        summary=f"{daily_struct.label.replace('_', ' ')}; {breakout_note}; {verdict}",
        what_changes_it={
            "bullish": (f"a close above {resistance.high:,.2f} on above-average volume"
                        if resistance else "a decisive close to new highs on heavy volume"),
            "bearish": (f"a close below {support.low:,.2f}, which breaks the structure"
                        if support else "a decisive close below the recent range on heavy volume"),
            "wait": phase_note,
        },
        quality=quality, notes=notes,
    )
