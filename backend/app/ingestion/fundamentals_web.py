"""Fetch real fundamentals for the expanded (technical-only) universe via yfinance.

yfinance is reachable from a RESIDENTIAL IP (only datacenter/CI get 429'd), so this runs
locally to backfill the ~10k US/India/Australia names added by expand_universe. It reuses the
tested fundamental engine (compute_ratios → score_fundamentals) on YahooProvider statements,
reblends the composite with the technical score already in the snapshot, and patches
screener.json + company/*.json. Resumable: names that already have a fundamental score are
skipped, so it can run in chunks. Names yfinance has no statements for stay technical-only.
"""

from __future__ import annotations

import contextlib
import json
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

from app.core.logging import get_logger
from app.core.snapshot_lock import snapshot_lock
from app.engines.composite.dimensions import quality_score, risk_score
from app.engines.composite.regime_modifier import apply_regime_modifier
from app.engines.composite.signals import derive_signal
from app.engines.fundamental.health import altman_z_score, piotroski_f_score
from app.engines.fundamental.ratios import MarketInputs, compute_ratios
from app.engines.fundamental.scoring import score_fundamentals
from app.ingestion.providers.base import StatementDTO
from app.ingestion.providers.yahoo import YahooProvider
from app.ingestion.tech_refresh import _f, _reblend
from app.models.enums import StatementPeriod

log = get_logger(__name__)


# Per-share / share-count fields are NOT flows — carry the latest, don't sum over 4 quarters.
_SHARE_FIELDS = {"weighted_shares", "shares_diluted", "shares_basic", "shares_outstanding"}


class _Row:
    """Attribute view over a values dict (missing field → None)."""

    def __init__(self, values: dict, fiscal_date):
        object.__setattr__(self, "_v", values)
        object.__setattr__(self, "fiscal_date", fiscal_date)

    def __getattr__(self, k):
        return self._v.get(k)


def _dtos_to_cache(dtos: list) -> list:
    return [[d.statement_type, d.fiscal_date.isoformat(), d.values] for d in dtos]


def _cache_to_dtos(raw: list) -> list:
    from datetime import date
    out = []
    for t, fd, v in raw:
        try:
            out.append(StatementDTO(statement_type=t, fiscal_date=date.fromisoformat(fd),
                                    period=StatementPeriod.QUARTER, values=v))
        except Exception:  # noqa: BLE001
            continue
    return out


def _get_statements(sym: str, provider: YahooProvider, cache_dir: Path | None,
                    force: bool = False, throttle: float = 0.0):
    """(quarterly, annual) statement DTOs — from the local cache if present, else yfinance
    (and cached). Caching avoids re-hitting yfinance on re-runs / re-scoring.

    ``force`` bypasses the cache read (but still refreshes it) — used after a company reports
    results, when the cached statements are by definition stale."""
    cf = (cache_dir / f"{sym}.json") if cache_dir else None
    if cf and cf.exists() and not force:
        try:
            raw = json.loads(cf.read_text(encoding="utf-8"))
            return _cache_to_dtos(raw.get("q", [])), _cache_to_dtos(raw.get("a", []))
        except (OSError, json.JSONDecodeError):
            pass
    if throttle:
        time.sleep(throttle)  # pace real fetches so yfinance doesn't start blocking us
    q = provider.get_statements(sym, StatementPeriod.QUARTER, limit=12)
    a = provider.get_statements(sym, StatementPeriod.ANNUAL, limit=5)
    if cf and (q or a):  # only cache real hits, so a transient 429 can be retried
        # OSError e.g. on a Windows-reserved filename — just skip the cache.
        with contextlib.suppress(OSError):
            cf.write_text(json.dumps({"q": _dtos_to_cache(q), "a": _dtos_to_cache(a)}),
                          encoding="utf-8")
    return q, a


def _group(dtos: list) -> dict[str, list]:
    by_type: dict[str, list] = {"income": [], "balance": [], "cashflow": []}
    for d in dtos:
        by_type.setdefault(d.statement_type, []).append(d)
    for lst in by_type.values():
        lst.sort(key=lambda d: d.fiscal_date)  # ascending
    return by_type


def _roll_ttm(dtos: list) -> tuple[list, list, list]:
    """Quarterly StatementDTOs → TTM series (same rule as ingestion.ttm.build_ttm_for_security):
    income & cash-flow flows summed over each trailing 4 quarters; balance carried per-quarter."""
    by_type = _group(dtos)
    inc: list = []
    cf: list = []
    for st, dst in (("income", inc), ("cashflow", cf)):
        rows = by_type.get(st, [])
        for i in range(3, len(rows)):
            window = rows[i - 3: i + 1]
            keys: set = set().union(*(w.values.keys() for w in window)) if window else set()
            vals: dict = {}
            for k in keys:
                present = [float(w.values[k]) for w in window if w.values.get(k) is not None]
                if len(present) == 4:  # only a clean 4-quarter TTM
                    vals[k] = present[-1] if k in _SHARE_FIELDS else sum(present)
            if vals:
                dst.append(_Row(vals, rows[i].fiscal_date))
    bal = [_Row(dict(r.values), r.fiscal_date) for r in by_type.get("balance", [])]
    return inc, bal, cf


def _score_one(price: float | None, regime, q: list, a: list):
    """Return (fund_score, ratios, metrics, (inc,bal,cf), period_label), or None.

    Prefers TTM (rolled from quarterly) for current-through-latest-quarter figures; falls back
    to annual when there aren't 4 clean quarters."""
    period_label = "ttm"
    inc, bal, cf = _roll_ttm(q) if q else ([], [], [])
    if not inc or not bal:  # not enough quarters → annual fallback
        ag = _group(a)
        inc = [_Row(d.values, d.fiscal_date) for d in ag.get("income", [])]
        bal = [_Row(d.values, d.fiscal_date) for d in ag.get("balance", [])]
        cf = [_Row(d.values, d.fiscal_date) for d in ag.get("cashflow", [])]
        period_label = "annual"
    if not inc or not bal:
        return None

    market = MarketInputs(price=price, shares_outstanding=None, market_cap=None)
    ratios = compute_ratios(inc, bal, cf, market)
    piotroski = piotroski_f_score(inc, bal, cf)
    ratios.piotroski_f = piotroski.score
    ratios.altman_z = altman_z_score(inc[-1], bal[-1], market.resolved_market_cap())
    metrics = {
        "roe": ratios.roe, "net_margin": ratios.net_margin, "roa": ratios.roa,
        "gross_margin": ratios.gross_margin, "revenue_growth": ratios.revenue_growth,
        "eps_growth": ratios.eps_growth, "debt_to_equity": ratios.debt_to_equity,
        "current_ratio": ratios.current_ratio, "interest_coverage": ratios.interest_coverage,
        "fcf_margin": ratios.fcf_margin,
        "piotroski_f": float(ratios.piotroski_f) if ratios.piotroski_f is not None else None,
        "altman_z": ratios.altman_z,
    }
    result = score_fundamentals(metrics)
    return result.score, ratios, metrics, (inc, bal, cf), period_label


def _statements_json(inc: list, bal: list, cf: list, period: str) -> dict:
    """Newest-first statement lists for the company page (matches the DB export shape)."""
    out: dict[str, list] = {}
    for st, rows in (("income", inc), ("balance", bal), ("cashflow", cf)):
        srt = sorted(rows, key=lambda r: r.fiscal_date, reverse=True)
        out[st] = [
            {**r._v, "period": period, "fiscal_date": r.fiscal_date.isoformat()}
            for r in srt
        ]
    return out


def _ratios_json(ratios) -> dict:
    keys = ("gross_margin", "operating_margin", "net_margin", "roe", "roa", "roic",
            "revenue_growth", "revenue_cagr_3y", "eps_growth", "eps_cagr_3y",
            "debt_to_equity", "current_ratio", "quick_ratio", "interest_coverage",
            "pe_ratio", "peg_ratio", "price_to_sales", "price_to_book", "ev_to_ebitda",
            "book_value_per_share", "dividend_yield", "piotroski_f", "altman_z")
    return {k: getattr(ratios, k, None) for k in keys}


def refresh_fundamentals_web(
    data_dir: str | Path, region: str, workers: int = 3, limit: int | None = None,
    cache_dir: str | Path | None = None, symbols: list[str] | None = None,
    force: bool = False, throttle: float = 0.4, cached_only: bool = False,
) -> dict[str, int]:
    """Take the snapshot lock, or skip - see app/core/snapshot_lock for why never blocking."""
    with snapshot_lock("refresh-fundamentals-web", data_dir) as ok:
        if not ok:
            return {"skipped": 1}
        return _refresh_fundamentals_web(
            data_dir, region, workers, limit, cache_dir, symbols, force, throttle, cached_only,
        )


def _refresh_fundamentals_web(
    data_dir: str | Path, region: str, workers: int = 3, limit: int | None = None,
    cache_dir: str | Path | None = None, symbols: list[str] | None = None,
    force: bool = False, throttle: float = 0.4, cached_only: bool = False,
) -> dict[str, int]:
    """Backfill fundamentals from yfinance.

    ``workers``/``throttle`` deliberately pace the fetching: yfinance blocks aggressive
    callers (a fast 6-worker run stalls in backoff and stops producing), so we use fewer
    concurrent workers and a short gap between requests. Cached names are unaffected — the
    gap only applies when a real fetch is needed.
    """
    out = Path(data_dir)
    cdir = out / "company"
    # Repo-root data/fund_cache/ (outside the deployed snapshot): backend/app/ingestion → AERP.
    cache = (Path(cache_dir) if cache_dir
             else Path(__file__).resolve().parents[3] / "data" / "fund_cache")
    cache.mkdir(parents=True, exist_ok=True)
    rows: list[dict] = json.loads((out / "screener.json").read_text(encoding="utf-8"))
    try:
        reg = json.loads((out / "macro_regime.json").read_text(encoding="utf-8"))
        regime_map = reg.get("countries", {})
    except (OSError, json.JSONDecodeError):
        regime_map = {}

    # region="all" backfills US+India+Australia concurrently in one pass (one writer, no race).
    wanted = {"us", "india", "australia"} if region == "all" else {region}

    def _is_target(r: dict) -> bool:
        # Skip names already scored AND names already attempted-with-no-usable-data (fund_na),
        # so phased runs advance instead of re-processing the same dataless names each pass.
        return (r.get("region") in wanted and r.get("fundamental_score") is None
                and not r.get("fund_na") and r.get("technical_score") is not None
                and r.get("provider_symbol"))

    if symbols:
        # Targeted refresh (e.g. companies that just reported results): take exactly these,
        # regardless of whether they already have a score — their numbers just changed.
        want = {s.strip().upper() for s in symbols if s.strip()}
        all_targets = [
            r for r in rows
            if (str(r.get("provider_symbol") or "").upper() in want
                or str(r.get("symbol") or "").upper() in want)
            and r.get("provider_symbol")
        ]
    else:
        all_targets = [r for r in rows if _is_target(r)]
    if cached_only:
        # Score only what's already been fetched: pure local work, no yfinance calls, so it
        # can't be rate-limited and finishes in seconds rather than hours.
        all_targets = [
            r for r in all_targets
            if (cache / f"{r['provider_symbol']}.json").exists()
        ]
    targets = all_targets[:limit] if limit is not None else all_targets

    provider = YahooProvider()

    def work(r: dict):
        # ok=False only on a real exception (transient 429 etc.) — those stay retryable;
        # ok=True with res=None means yfinance had no usable statements → mark fund_na.
        try:
            q, a = _get_statements(
                r["provider_symbol"], provider, cache, force=force, throttle=throttle
            )
            return r, _score_one(_f(r.get("price")), regime_map.get(r.get("region")), q, a), True
        except Exception:  # noqa: BLE001 - one bad ticker shouldn't stop the batch
            return r, None, False

    updated = 0
    with ThreadPoolExecutor(max_workers=workers) as pool:
        # as_completed (not map): process each result the moment it finishes, so one slow
        # rate-limited fetch can't head-of-line-block the cached/fast ones behind it.
        futures = [pool.submit(work, r) for r in targets]
        for fut in as_completed(futures):
            r, res, ok = fut.result()
            if res is None:
                if ok:
                    r["fund_na"] = True  # attempted, no usable statements — don't retry
                continue
            fund, ratios, metrics, (inc, bal, cf_rows), period_label = res
            if fund is None:
                r["fund_na"] = True
                continue
            tech = _f(r.get("technical_score"))
            de = _f(ratios.debt_to_equity)
            # Quality + risk come straight from the same ratios (same engine the curated
            # pipeline uses), so expanded names get the full score set — not just fund+tech.
            # Momentum needs price indicators, so tech_refresh fills that leg on its daily run.
            qual, _q = quality_score(ratios)
            risk, _r = risk_score(None, ratios)
            base, cov, present = _reblend(fund, tech, None, _f(qual), _f(risk))
            if base is None:
                continue
            comp, _bd = apply_regime_modifier(base, regime_map.get(r.get("region")), de)
            sig = derive_signal(comp, cov, present)

            r["fundamental_score"] = round(fund, 2)
            r["composite_score"] = comp
            r["signal"] = sig.signal.value
            r["signal_label"] = sig.label
            r["roe"] = ratios.roe
            r["debt_to_equity"] = ratios.debt_to_equity
            r["revenue_growth"] = ratios.revenue_growth
            r["eps_growth"] = ratios.eps_growth
            r["pe_ttm"] = ratios.pe_ratio

            cjson = cdir / f"{r['provider_symbol']}.json"
            if cjson.exists():
                try:
                    d = json.loads(cjson.read_text(encoding="utf-8"))
                    d["statements"] = _statements_json(inc, bal, cf_rows, period_label)
                    d["ratios"] = _ratios_json(ratios)
                    d["fundamentals"] = {
                        "pe_ttm": ratios.pe_ratio, "roe": ratios.roe,
                        "debt_to_equity": ratios.debt_to_equity,
                        "revenue_growth": ratios.revenue_growth,
                        "eps_growth": ratios.eps_growth, "net_margin": ratios.net_margin,
                        "dividend_yield": ratios.dividend_yield,
                    }
                    if isinstance(d.get("scores"), dict):
                        d["scores"]["fundamental"] = round(fund, 2)
                        d["scores"]["composite"] = comp
                        if qual is not None:
                            d["scores"]["quality"] = round(qual, 2)
                        if risk is not None:
                            d["scores"]["risk"] = round(risk, 2)
                    if isinstance(d.get("signal"), dict):
                        d["signal"]["signal_type"] = sig.signal.value
                        d["signal"]["label"] = sig.label
                    cjson.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
                except (OSError, json.JSONDecodeError):
                    pass
            updated += 1
            # Periodic checkpoint so a long run that dies mid-way (machine sleep etc.) never
            # loses progress — the screener rows patched so far persist and a re-run resumes.
            if updated % 400 == 0:
                (out / "screener.json").write_text(json.dumps(rows), encoding="utf-8")

    rows.sort(key=lambda r: (r.get("composite_score") is not None,
                             r.get("composite_score") or 0), reverse=True)
    (out / "screener.json").write_text(json.dumps(rows), encoding="utf-8")
    remaining = sum(1 for r in rows if _is_target(r))
    result: dict[str, Any] = {"targets": len(targets), "updated": updated, "remaining": remaining}
    log.info("refresh-fundamentals-web[%s]: %s", region, result)
    return result
