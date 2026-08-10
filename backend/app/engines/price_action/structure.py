"""Swing points, market structure and support/resistance — from price alone.

Everything here is a MEASUREMENT taken off the candles: where price turned, how far it travelled,
how often a level was tested. No smoothing, no oscillators, nothing with a period parameter
standing in for a judgement. The rule the whole module follows is that a level matters because
price repeatedly reacted to it, not because a formula emitted it.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class Swing:
    """A confirmed turning point: the bar that was the local extreme."""

    index: int
    date: str
    price: float
    kind: str  # "high" | "low"


@dataclass(slots=True)
class Zone:
    """A support or resistance ZONE, because price reacts across a range, not at a number."""

    low: float
    high: float
    kind: str            # "support" | "resistance"
    touches: int
    last_touch: str
    strength: str        # "major" | "minor"
    evidence: str

    @property
    def mid(self) -> float:
        return (self.low + self.high) / 2


@dataclass(slots=True)
class Structure:
    label: str                       # strong_uptrend ... strong_downtrend, range, transitions
    sequence: list[str] = field(default_factory=list)   # HH / HL / LH / LL, oldest first
    note: str = ""


def swings(high: list[float], low: list[float], dates: list[str], left: int = 3,
           right: int = 3) -> list[Swing]:
    """Pivot highs and lows: a bar higher (lower) than `left` before and `right` after it.

    `right` bars of confirmation is the whole point - a high is only a high once price has
    failed to exceed it for a few sessions. It also means the newest few bars can never be
    swings, which is correct: a turning point you can see the same day is a guess.
    """
    out: list[Swing] = []
    n = len(high)
    for i in range(left, n - right):
        window_h = high[i - left:i + right + 1]
        window_l = low[i - left:i + right + 1]
        if high[i] == max(window_h) and window_h.count(high[i]) == 1:
            out.append(Swing(i, dates[i], high[i], "high"))
        elif low[i] == min(window_l) and window_l.count(low[i]) == 1:
            out.append(Swing(i, dates[i], low[i], "low"))
    return out


def label_sequence(points: list[Swing]) -> list[str]:
    """Turn alternating swings into the HH / HL / LH / LL sequence traders actually read."""
    seq: list[str] = []
    last_high: float | None = None
    last_low: float | None = None
    for s in points:
        if s.kind == "high":
            if last_high is not None:
                seq.append("HH" if s.price > last_high else "LH")
            last_high = s.price
        else:
            if last_low is not None:
                seq.append("HL" if s.price > last_low else "LL")
            last_low = s.price
    return seq


def classify_structure(points: list[Swing], close: list[float]) -> Structure:
    """Name the structure from the last few swings, and say why in price terms.

    Read off the SEQUENCE rather than off a trend line or an average, so the answer is the one
    a person reading the chart would give: higher lows and higher highs is an uptrend, and it
    stops being one when a higher low fails.
    """
    if len(points) < 3:
        return Structure("insufficient_history", [], "fewer than three confirmed swings")

    seq = label_sequence(points)
    recent = seq[-4:]
    ups = sum(1 for x in recent if x in ("HH", "HL"))
    downs = sum(1 for x in recent if x in ("LH", "LL"))

    highs = [s for s in points if s.kind == "high"]
    lows = [s for s in points if s.kind == "low"]

    def _fmt(v: float) -> str:
        return f"{v:,.2f}"

    note = ""
    if len(lows) >= 2 and len(highs) >= 1:
        note = (f"last swing low {_fmt(lows[-1].price)} on {lows[-1].date}, "
                f"prior {_fmt(lows[-2].price)}; last swing high {_fmt(highs[-1].price)}")

    if not recent:
        return Structure("range", seq, note)

    # A transition is the interesting case and it has a specific shape: the old sequence broke
    # but the new one has not been established. Calling those "uptrend" or "downtrend" is how a
    # topping chart gets read as strength.
    if ups == len(recent):
        label = "strong_uptrend"
    elif downs == len(recent):
        label = "strong_downtrend"
    elif ups > downs:
        label = "weak_uptrend"
    elif downs > ups:
        label = "weak_downtrend"
    else:
        label = "range"

    # A transition needs BOTH halves of the sequence to turn, judged separately. Reading it off
    # the single most recent label calls every sharp pullback a top: Apple printed a new high at
    # 344.57 and then a lower low at 300, and that one LL was enough to label a stock at all-time
    # highs "uptrend to distribution". Distribution means the highs stopped advancing AND the
    # lows started failing - a lower high with a lower low. One deep pullback after a new high
    # is a pullback.
    high_labels = [x for x in seq if x in ("HH", "LH")]
    low_labels = [x for x in seq if x in ("HL", "LL")]
    last_high_label = high_labels[-1] if high_labels else None
    last_low_label = low_labels[-1] if low_labels else None

    if (label in ("weak_uptrend", "range") and last_high_label == "LH"
            and last_low_label == "LL" and ups >= 1):
        label = "uptrend_to_distribution"
    if (label in ("weak_downtrend", "range") and last_high_label == "HH"
            and last_low_label == "HL" and downs >= 1):
        label = "downtrend_to_accumulation"
    return Structure(label, seq, note)


def _cluster(levels: list[tuple[float, str]], tolerance: float) -> list[list[tuple[float, str]]]:
    """Group prices into zones, measuring from the group's FLOOR rather than its last member.

    Chaining off the previous member is the obvious implementation and it is wrong: each price
    only has to be within tolerance of the one before it, so a long ladder of swings merges into
    one enormous band. It produced a single Apple "support zone" running 207 to 228 - a ten per
    cent range, which is not a level, it is most of the chart. Anchoring on the group's floor
    caps a zone at the tolerance width no matter how many points fall inside it.
    """
    if not levels:
        return []
    ordered = sorted(levels, key=lambda x: x[0])
    groups: list[list[tuple[float, str]]] = [[ordered[0]]]
    for price, when in ordered[1:]:
        if price - groups[-1][0][0] <= tolerance:
            groups[-1].append((price, when))
        else:
            groups.append([(price, when)])
    return groups


def zones(points: list[Swing], close: list[float], high: list[float], low: list[float],
          last_price: float, max_per_side: int = 3) -> list[Zone]:
    """The handful of levels that actually matter, as zones, with the evidence for each.

    Deliberately few. A chart with fourteen lines on it has no levels at all, so only the most
    tested clusters on each side survive - and a level's claim rests on how many times price
    turned there, not on how neatly it can be drawn.
    """
    if not points or not last_price:
        return []
    # Zone width scales with the instrument: 1.5% of price is a tight band on a large cap and a
    # sensible one on a penny stock, where a fixed cash tolerance would merge everything.
    tolerance = last_price * 0.015

    out: list[Zone] = []
    for kind, want in (("high", "resistance"), ("low", "support")):
        raw = [(s.price, s.date) for s in points if s.kind == kind]
        clusters = _cluster(raw, tolerance)
        scored: list[Zone] = []
        for group in clusters:
            # One swing is not a level. The brief is explicit that a level earns its place by
            # being repeatedly respected, and publishing single-touch highs as "resistance" is
            # how a chart ends up with a dozen meaningless lines on it.
            if len(group) < 2:
                continue
            prices = [p for p, _ in group]
            touches = len(group)
            lo, hi = min(prices), max(prices)
            # A zone only counts as support/resistance relative to where price is NOW. Old
            # resistance that price is trading above has become support, and saying otherwise
            # is the most common way these charts get read backwards.
            side = want
            if want == "resistance" and hi < last_price:
                side = "support"
            elif want == "support" and lo > last_price:
                side = "resistance"
            strength = "major" if touches >= 3 else "minor"
            flip = " (former resistance now below price)" if side != want and want == "resistance" \
                else " (former support now above price)" if side != want else ""
            scored.append(Zone(
                low=round(lo, 4), high=round(hi, 4), kind=side, touches=touches,
                last_touch=max(d for _, d in group), strength=strength,
                evidence=f"{touches} swing {'highs' if kind == 'high' else 'lows'} clustered "
                         f"between {lo:,.2f} and {hi:,.2f}{flip}",
            ))
        out.extend(scored)

    # Keep the best few per side: most tested first, then nearest to price, because a level
    # twenty percent away is not what a swing trade turns on.
    picked: list[Zone] = []
    for side in ("support", "resistance"):
        same = [z for z in out if z.kind == side]
        same.sort(key=lambda z: (-z.touches, abs(z.mid - last_price)))
        picked.extend(same[:max_per_side])
    picked.sort(key=lambda z: z.mid)
    return picked


def nearest(zones_: list[Zone], last_price: float, side: str) -> Zone | None:
    """The closest support below, or resistance above - the two levels a trade hangs on."""
    if side == "support":
        below = [z for z in zones_ if z.kind == "support" and z.high <= last_price]
        return max(below, key=lambda z: z.high) if below else None
    above = [z for z in zones_ if z.kind == "resistance" and z.low >= last_price]
    return min(above, key=lambda z: z.low) if above else None
