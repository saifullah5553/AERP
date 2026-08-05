"""Put a price series on one basis, so a share split is not read as a crash.

A 5:1 split quintuples the share count and divides the price by five. Nothing was lost, but a
holding bought before and sold after shows an 80% loss unless the history is restated. KOHC
split 5/1 in August 2025 and the rebalance ledger reported -73.29%; DLL split 10:1 and reported
-88.92%.

We cannot delegate this. For PSX, Yahoo's `adjclose` is identical to `close` - no adjustment is
applied at all - and its raw series is internally inconsistent around the event: KOHC ran
457.81, 92.21, 93.50, 467.51, 467.25, 98.68 across six sessions, adjusting some days and not
others. It also reported the same 5:1 split twice, on consecutive dates.

So the split events give the WHEN and the HOW MUCH, and this module rebuilds the series:

  * duplicate events are collapsed - the same ratio within a few days is one corporate action
    reported twice, not two splits
  * bars already carrying the adjustment are detected and left alone, rather than divided again
  * everything before the event is divided by the ratio, volume multiplied

The output is a continuous series. It is a total-return-style restatement of history, which is
what a return calculation needs; the price a share last traded at is unchanged.
"""

from __future__ import annotations

from datetime import UTC, datetime

# Two reports of the same ratio inside this window are one corporate action. Yahoo listed
# KOHC's 5:1 on both 21 and 25 August.
DUPLICATE_DAYS = 10
# How close a neighbouring bar must be to the split ratio before it is treated as already
# adjusted rather than as a real price move.
RATIO_TOLERANCE = 0.15


def parse_splits(events: dict | None) -> list[tuple[str, float]]:
    """[(date, ratio)] from a Yahoo chart `events` block, newest last, deduplicated."""
    raw: list[tuple[str, float]] = []
    for ev in ((events or {}).get("splits") or {}).values():
        try:
            when = datetime.fromtimestamp(int(ev["date"]), UTC).date()
            num = float(ev.get("numerator") or 0)
            den = float(ev.get("denominator") or 0)
        except (TypeError, ValueError, KeyError, OSError):
            continue
        if num > 0 and den > 0 and abs(num / den - 1.0) > 0.01:
            raw.append((when.isoformat(), num / den))

    raw.sort()
    out: list[tuple[str, float]] = []
    for when, ratio in raw:
        if out:
            prev_when, prev_ratio = out[-1]
            same_ratio = abs(ratio - prev_ratio) < 0.01
            gap = (datetime.fromisoformat(when).date()
                   - datetime.fromisoformat(prev_when).date()).days
            if same_ratio and gap <= DUPLICATE_DAYS:
                # The same action reported twice: keep the LATER date, which is the ex-date.
                # Checked against two known splits - KOHC 5:1 (Yahoo says 21 and 25 Aug 2025,
                # actual 25 Aug) and KTML 5:1 (11 and 15 Sep 2025, actual 15 Sep). Taking the
                # earlier one divides the days in between, which were still trading on the old
                # basis, and leaves the repair pass to undo a mistake we need not make.
                out[-1] = (when, ratio)
                continue
        out.append((when, ratio))
    return out


def _median(values: list[float]) -> float:
    ordered = sorted(values)
    return ordered[len(ordered) // 2]


def _repair_outliers(bars: dict[str, list], ratio: float, window: int = 5) -> int:
    """Undo the adjustment on bars the vendor had already adjusted before we divided them.

    Every pre-split bar is divided, because that is right for almost all of them. The handful
    Yahoo adjusted early then sit a factor BELOW their neighbours, and a local median finds
    them without needing to know the price level - which is the part that cannot be assumed,
    since a stock legitimately traded at very different levels five years ago.
    """
    days = sorted(bars)
    closes: dict[str, float] = {}
    for d in days:
        try:
            c = float(bars[d][4])
        except (TypeError, ValueError, IndexError):
            continue
        if c > 0:
            closes[d] = c

    ordered = [d for d in days if d in closes]
    fixed = 0
    for i, d in enumerate(ordered):
        near = [closes[x] for x in ordered[max(0, i - window): i + window + 1] if x != d]
        if len(near) < 4:
            continue
        local = _median(near)
        if local <= 0:
            continue
        # Sitting at roughly a factor of `ratio` below its neighbours: it was divided twice.
        if abs((local / closes[d]) / ratio - 1.0) < RATIO_TOLERANCE:
            row = bars[d]
            for j in (1, 2, 3, 4):
                try:
                    if row[j] not in (None, ""):
                        row[j] = float(row[j]) * ratio
                except (TypeError, ValueError):
                    continue
            try:
                if row[5] not in (None, ""):
                    row[5] = float(row[5]) / ratio
            except (TypeError, ValueError):
                pass
            fixed += 1
    return fixed


SEARCH_DAYS = 20


def _boundary(bars: dict[str, list], reported: str, ratio: float) -> str:
    """The day the series actually changes basis, found in the prices themselves.

    The reported date cannot be trusted on its own. Yahoo files these splits twice, days apart,
    and neither copy reliably matches the ex-date: KOHC came through as 21 and 25 August, KTML
    as 11 and 15 September. Taking the earlier divides days that had already been adjusted;
    taking the later divides days still on the old basis, which put DLL back at -88.9%.

    So the reported date only says roughly WHEN to look. The step down by the split ratio says
    exactly where, and the LAST such step is the real one - the vendor's half-adjusted days
    produce earlier ones that are noise.
    """
    days = sorted(bars)
    window = [d for d in days
              if abs((datetime.fromisoformat(d).date()
                      - datetime.fromisoformat(reported).date()).days) <= SEARCH_DAYS]
    found = None
    for prev, cur in zip(window, window[1:], strict=False):
        try:
            a, b = float(bars[prev][4]), float(bars[cur][4])
        except (TypeError, ValueError, IndexError):
            continue
        if a > 0 and b > 0 and abs((a / b) / ratio - 1.0) < RATIO_TOLERANCE:
            found = cur
    return found or reported


def adjust(bars: dict[str, list], splits: list[tuple[str, float]]) -> tuple[dict[str, list], int]:
    """Restate `bars` (date -> [date, o, h, l, c, v]) onto the post-split basis.

    Two passes per split, and the order matters. Divide everything before the event - correct
    for the overwhelming majority - then put back the few the vendor had already adjusted,
    found by how far they sit below their own neighbours rather than by any assumed price
    level. Applied newest split first so several splits compound correctly.
    """
    if not bars or not splits:
        return bars, 0

    changed = 0
    for reported, ratio in reversed(splits):
        when = _boundary(bars, reported, ratio)
        before = sorted(d for d in bars if d < when)
        if not before:
            continue
        for d in before:
            row = bars[d]
            for j in (1, 2, 3, 4):
                try:
                    if row[j] not in (None, ""):
                        row[j] = float(row[j]) / ratio
                except (TypeError, ValueError):
                    continue
            try:
                if row[5] not in (None, ""):
                    row[5] = float(row[5]) * ratio
            except (TypeError, ValueError):
                pass
            changed += 1
        changed -= _repair_outliers(bars, ratio)
    return bars, max(changed, 0)
