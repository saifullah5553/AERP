"""Post-condition checks: did the refresh actually refresh anything?

WHY THIS EXISTS. Every layer of this pipeline is deliberately fail-open. 35 workflow steps
end in `|| true`, ~40 engine calls swallow their exceptions, and the export merges with the
committed snapshot so a step that produced nothing carries the previous value forward. Each
choice is defensible on its own - a network blip should not blank the dashboard - but
together they mean:

    step fails  ->  step skipped  ->  old value carried forward  ->  run reports success

There was no state in which the system said "this is stale". That is why something was always
quietly out of date: PSX bars stopped on 3 August and nothing noticed for nineteen days;
the daily refresh was cancelled 99 times out of 100 and nothing noticed for weeks; a third of
all grade labels contradicted their own score and nothing noticed at all. None of those were
errors. They were absences, and the pipeline has no opinion about absences.

So this module is the missing half: it does not fetch anything, it CHECKS. Run it after a
refresh and it fails the run when an artifact is older than it should be. A stale artifact
becomes a red run today instead of a discovery weeks later.

Deliberately NOT fail-open. This is the one place that must be allowed to fail.
"""

from __future__ import annotations

import datetime
import gzip
import json
from dataclasses import dataclass
from pathlib import Path

from app.core.logging import get_logger

log = get_logger(__name__)

MARKETS = ("psx", "us", "india", "australia", "gcc", "dfm")

# How many days behind an artifact may fall before it is a problem. Generous enough to cover
# a weekend plus a public holiday on either side, tight enough that a fortnight of silence
# cannot pass for normal.
MAX_AGE_DAYS = {
    "prices": 5,
    "bars": 5,
    "snapshot": 2,
}
# Coverage floors. A market that suddenly scores half as many companies has broken, even
# though every individual number in it looks fine.
MIN_SCORED_RATIO = 0.80
MIN_GRADE_AGREEMENT = 1.0      # a label may never contradict its own score


@dataclass
class Check:
    name: str
    ok: bool
    detail: str

    def line(self) -> str:
        return f"{'OK  ' if self.ok else 'FAIL'} {self.name:38s} {self.detail}"


def _age(day: str | None, today: datetime.date) -> int | None:
    if not day:
        return None
    try:
        return (today - datetime.date.fromisoformat(str(day)[:10])).days
    except ValueError:
        return None


def check_snapshot(data_dir: Path, today: datetime.date) -> list[Check]:
    out: list[Check] = []
    rows = json.loads((data_dir / "screener.json").read_text(encoding="utf-8"))
    eq = [r for r in rows if (r.get("asset_class") or "equity") == "equity"]

    # 1. Prices, per market. Aggregates hide a single dead market, so never check the total.
    for m in MARKETS:
        days = [r.get("price_as_of") for r in rows if r.get("region") == m and r.get("price_as_of")]
        if not days:
            out.append(Check(f"prices[{m}]", False, "no priced rows at all"))
            continue
        age = _age(max(days), today)
        out.append(Check(f"prices[{m}]", age is not None and age <= MAX_AGE_DAYS["prices"],
                         f"newest {max(days)} ({age}d), n={len(days)}"))

    # 2. Scores, per market, by ratio rather than count - a market that halves has broken.
    for m in MARKETS:
        mk = [r for r in eq if r.get("region") == m]
        if not mk:
            continue
        scored = [r for r in mk if r.get("quality_score") is not None]
        ratio = len(scored) / len(mk)
        out.append(Check(f"scored[{m}]", ratio >= MIN_SCORED_RATIO,
                         f"{len(scored)}/{len(mk)} ({ratio:.0%})"))

    # 3. The label may never contradict the number it sits beside.
    from app.engines.fundamental.adaptive import rating_for

    scored = [r for r in eq if r.get("quality_score") is not None]
    bad = [r for r in scored
           if r.get("quality_grade")
           and rating_for(float(r["quality_score"])) != r["quality_grade"]]
    out.append(Check("grade matches score", not bad,
                     f"{len(scored) - len(bad)}/{len(scored)} agree"
                     + (f", first bad: {bad[0].get('provider_symbol')}" if bad else "")))
    return out


def check_bars(repo_root: Path, today: datetime.date) -> list[Check]:
    out: list[Check] = []
    for m in (*MARKETS, "global"):
        p = repo_root / "data" / "prices" / f"{m}.json.gz"
        if not p.exists():
            out.append(Check(f"bars[{m}]", False, "pack missing"))
            continue
        try:
            with gzip.open(p, "rt", encoding="utf-8") as fh:
                d = json.loads(fh.read())
        except (OSError, json.JSONDecodeError) as exc:
            out.append(Check(f"bars[{m}]", False, f"unreadable: {type(exc).__name__}"))
            continue
        newest = max((v["d"][-1] for v in d.values() if v.get("d")), default=None)
        age = _age(newest, today)
        out.append(Check(f"bars[{m}]", age is not None and age <= MAX_AGE_DAYS["bars"],
                         f"newest {newest} ({age}d), {len(d)} symbols"))
    return out


def check_files(data_dir: Path, today: datetime.date) -> list[Check]:
    out: list[Check] = []
    for name in ("screener.json", "macro_regime.json", "model_portfolio.json", "meta.json"):
        p = data_dir / name
        if not p.exists():
            out.append(Check(f"file[{name}]", False, "missing"))
            continue
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            out.append(Check(f"file[{name}]", False, f"unreadable: {type(exc).__name__}"))
            continue
        stamp = None
        if isinstance(d, dict):
            for k in ("generated_at", "updated_at", "as_of"):
                if d.get(k):
                    stamp = str(d[k])
                    break
        if stamp is None:
            out.append(Check(f"file[{name}]", True, "no timestamp field (not checked)"))
            continue
        age = _age(stamp, today)
        out.append(Check(f"file[{name}]", age is not None and age <= MAX_AGE_DAYS["snapshot"],
                         f"{stamp[:19]} ({age}d)"))
    return out


def verify(data_dir: str | Path, repo_root: str | Path | None = None,
           today: datetime.date | None = None) -> tuple[list[Check], int]:
    """Every check, and the number that failed."""
    data_dir = Path(data_dir)
    repo_root = Path(repo_root) if repo_root else data_dir.parents[2]
    today = today or datetime.date.today()

    checks = check_snapshot(data_dir, today) + check_bars(repo_root, today) \
        + check_files(data_dir, today)
    failed = sum(1 for c in checks if not c.ok)
    for c in checks:
        (log.warning if not c.ok else log.info)("freshness: %s", c.line())
    log.info("freshness: %d checks, %d failed", len(checks), failed)
    return checks, failed
