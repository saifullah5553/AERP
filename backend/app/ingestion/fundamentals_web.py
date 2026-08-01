"""Fetch real fundamentals for the expanded (technical-only) universe via yfinance.

yfinance is reachable from a RESIDENTIAL IP (only datacenter/CI get 429'd), so this runs
locally to backfill the ~10k US/India/Australia names added by expand_universe. It reuses the
tested fundamental engine (compute_ratios → score_fundamentals) on YahooProvider statements,
reblends the composite with the technical score already in the snapshot, and patches
screener.json + company/*.json. Resumable: names that already have a fundamental score are
skipped, so it can run in chunks. Names yfinance has no statements for stay technical-only.
"""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from app.core.logging import get_logger
from app.engines.composite.regime_modifier import apply_regime_modifier
from app.engines.composite.signals import derive_signal
from app.engines.fundamental.health import altman_z_score, piotroski_f_score
from app.engines.fundamental.ratios import MarketInputs, compute_ratios
from app.engines.fundamental.scoring import score_fundamentals
from app.ingestion.providers.yahoo import YahooProvider
from app.ingestion.tech_refresh import _f, _reblend
from app.models.enums import StatementPeriod

log = get_logger(__name__)


class _Row:
    """Attribute view over a StatementDTO.values dict (missing field → None)."""

    def __init__(self, values: dict, fiscal_date):
        object.__setattr__(self, "_v", values)
        object.__setattr__(self, "fiscal_date", fiscal_date)

    def __getattr__(self, k):
        return self._v.get(k)


def _score_one(sym: str, price: float | None, regime, provider: YahooProvider):
    """Return (fund_score, ratios, metrics, statements_by_type) for a symbol, or None."""
    dtos = provider.get_statements(sym, StatementPeriod.ANNUAL, limit=5)
    if not dtos:
        return None
    by_type: dict[str, list] = {"income": [], "balance": [], "cashflow": []}
    for d in dtos:
        by_type.setdefault(d.statement_type, []).append(d)
    for lst in by_type.values():
        lst.sort(key=lambda d: d.fiscal_date)  # ascending, as the engine expects
    inc = [_Row(d.values, d.fiscal_date) for d in by_type.get("income", [])]
    bal = [_Row(d.values, d.fiscal_date) for d in by_type.get("balance", [])]
    cf = [_Row(d.values, d.fiscal_date) for d in by_type.get("cashflow", [])]
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
    return result.score, ratios, metrics, by_type


def _statements_json(by_type: dict[str, list]) -> dict:
    """Newest-first statement lists for the company page (matches the DB export shape)."""
    out: dict[str, list] = {}
    for st in ("income", "balance", "cashflow"):
        rows = sorted(by_type.get(st, []), key=lambda d: d.fiscal_date, reverse=True)
        out[st] = [
            {**d.values, "period": "annual", "fiscal_date": d.fiscal_date.isoformat()}
            for d in rows
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
    data_dir: str | Path, region: str, workers: int = 6, limit: int | None = None
) -> dict[str, int]:
    out = Path(data_dir)
    cdir = out / "company"
    rows: list[dict] = json.loads((out / "screener.json").read_text(encoding="utf-8"))
    try:
        reg = json.loads((out / "macro_regime.json").read_text(encoding="utf-8"))
        regime_map = reg.get("countries", {})
    except (OSError, json.JSONDecodeError):
        regime_map = {}
    regime = regime_map.get(region)

    targets = [
        r for r in rows
        if r.get("region") == region and r.get("fundamental_score") is None
        and r.get("technical_score") is not None and r.get("provider_symbol")
    ]
    if limit is not None:
        targets = targets[:limit]

    provider = YahooProvider()

    def work(r: dict):
        try:
            return r, _score_one(r["provider_symbol"], _f(r.get("price")), regime, provider)
        except Exception:  # noqa: BLE001 - one bad ticker shouldn't stop the batch
            return r, None

    updated = 0
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for r, res in pool.map(work, targets):
            if res is None:
                continue
            fund, ratios, metrics, by_type = res
            if fund is None:
                continue
            tech = _f(r.get("technical_score"))
            de = _f(ratios.debt_to_equity)
            base, cov, present = _reblend(fund, tech, None, None, None)
            if base is None:
                continue
            comp, _bd = apply_regime_modifier(base, regime, de)
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

            cf = cdir / f"{r['provider_symbol']}.json"
            if cf.exists():
                try:
                    d = json.loads(cf.read_text(encoding="utf-8"))
                    d["statements"] = _statements_json(by_type)
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
                    if isinstance(d.get("signal"), dict):
                        d["signal"]["signal_type"] = sig.signal.value
                        d["signal"]["label"] = sig.label
                    cf.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
                except (OSError, json.JSONDecodeError):
                    pass
            updated += 1

    rows.sort(key=lambda r: (r.get("composite_score") is not None,
                             r.get("composite_score") or 0), reverse=True)
    (out / "screener.json").write_text(json.dumps(rows), encoding="utf-8")
    result: dict[str, Any] = {"targets": len(targets), "updated": updated}
    log.info("refresh-fundamentals-web[%s]: %s", region, result)
    return result
