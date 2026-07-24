"""AERP management CLI — run the whole pipeline without Celery/broker/auth.

Useful for local runs, demos, and cron jobs. Every command operates directly on
the configured database (``DATABASE_URL``; point it at SQLite for a keyless local
run, e.g. ``DATABASE_URL=sqlite+pysqlite:///./aerp.db``).

Examples:
    python -m app.cli init-db
    python -m app.cli seed
    python -m app.cli ingest-psx
    python -m app.cli ingest-macro
    python -m app.cli compute
    python -m app.cli all                 # seed → ingest everything → compute
"""

from __future__ import annotations

import argparse
from collections.abc import Callable

from app.core.logging import get_logger
from app.models.enums import MarketRegion

log = get_logger("aerp.cli")


def _region(value: str | None) -> MarketRegion | None:
    return MarketRegion(value) if value else None


def cmd_init_db(args: argparse.Namespace) -> None:
    """Create all tables (local/dev convenience; production uses Alembic)."""
    from app.db.session import engine
    from app.models import Base

    Base.metadata.create_all(bind=engine)
    log.info("Schema created on %s", engine.url.render_as_string(hide_password=True))


def cmd_seed(args: argparse.Namespace) -> None:
    from app.db.seed import seed_all

    log.info("seed: %s", seed_all())


def cmd_ingest_psx(args: argparse.Namespace) -> None:
    from app.db.session import session_scope
    from app.ingestion.psx_csv import ingest_psx_csv

    with session_scope() as db:
        log.info("ingest-psx: %s", ingest_psx_csv(db))


def cmd_ingest_macro(args: argparse.Namespace) -> None:
    from app.db.session import session_scope
    from app.ingestion.macro import WorldBankClient, ingest_macro

    with session_scope() as db:
        log.info("ingest-macro: %s", ingest_macro(db, WorldBankClient()))


def cmd_ingest_quotes(args: argparse.Namespace) -> None:
    from app.db.session import session_scope
    from app.ingestion.pipeline import refresh_quotes
    from app.ingestion.registry import ProviderRegistry

    with session_scope() as db:
        r = refresh_quotes(db, ProviderRegistry(), region=_region(args.region), limit=args.limit)
        log.info("ingest-quotes: requested=%d resolved=%d", r.requested, r.resolved)


def cmd_backfill(args: argparse.Namespace) -> None:
    from app.db.session import session_scope
    from app.ingestion.pipeline import backfill_daily
    from app.ingestion.registry import ProviderRegistry

    with session_scope() as db:
        n = backfill_daily(db, ProviderRegistry(), region=_region(args.region), limit=args.limit)
        log.info("backfill: %d bars", n)


def cmd_ingest_fundamentals(args: argparse.Namespace) -> None:
    from app.db.session import session_scope
    from app.ingestion.pipeline import ingest_fundamentals
    from app.ingestion.registry import ProviderRegistry

    with session_scope() as db:
        log.info("ingest-fundamentals: %s",
                 ingest_fundamentals(db, ProviderRegistry(), region=_region(args.region),
                                     limit=args.limit))


def cmd_load_universe(args: argparse.Namespace) -> None:
    from app.db.session import session_scope
    from app.ingestion.pipeline import load_universe
    from app.ingestion.registry import ProviderRegistry

    providers = args.providers.split(",") if args.providers else None
    with session_scope() as db:
        log.info("load-universe: %s", load_universe(db, ProviderRegistry(), providers))


def cmd_load_us_universe(args: argparse.Namespace) -> None:
    from app.db.session import session_scope
    from app.ingestion.us_universe import SECClient, ingest_us_universe

    with session_scope() as db:
        log.info("load-us-universe: %s", ingest_us_universe(db, SECClient(), limit=args.limit))


def cmd_ingest_insider(args: argparse.Namespace) -> None:
    from app.db.session import session_scope
    from app.ingestion.insider import EdgarClient, ingest_insider

    with session_scope() as db:
        log.info("ingest-insider: %s", ingest_insider(db, EdgarClient(), limit=args.limit))


def cmd_ingest_psx_insider(args: argparse.Namespace) -> None:
    from app.db.session import session_scope
    from app.ingestion.psx_insider import ingest_psx_insider

    with session_scope() as db:
        log.info("ingest-psx-insider: %s", ingest_psx_insider(db))


def cmd_ingest_news(args: argparse.Namespace) -> None:
    from app.db.session import session_scope
    from app.ingestion.news import GoogleNewsClient, ingest_news

    with session_scope() as db:
        log.info("ingest-news: %s", ingest_news(db, GoogleNewsClient(), limit=args.limit))


def cmd_compute(args: argparse.Namespace) -> None:
    """Run every analytics engine in dependency order."""
    from app.db.session import session_scope
    from app.engines.composite.engine import compute_all as composite_all
    from app.engines.forex.engine import compute_all as forex_all
    from app.engines.fundamental.engine import compute_all as fundamental_all
    from app.engines.insider.engine import compute_all as insider_all
    from app.engines.patterns.engine import compute_all as patterns_all
    from app.engines.technical.engine import compute_all as technical_all

    with session_scope() as db:
        log.info("fundamentals: %s", fundamental_all(db, limit=args.limit))
        log.info("forex: %s", forex_all(db, limit=args.limit))
        log.info("technical: %s", technical_all(db, limit=args.limit))
        log.info("patterns: %s", patterns_all(db, limit=args.limit))
        log.info("insider: %s", insider_all(db, limit=args.limit))
        log.info("composite: %s", composite_all(db, limit=args.limit))


def cmd_all(args: argparse.Namespace) -> None:
    """Full local pipeline: schema → seed → ingest everything → compute."""
    cmd_init_db(args)
    cmd_seed(args)
    cmd_load_universe(argparse.Namespace(providers="binance,psx"))
    cmd_load_us_universe(argparse.Namespace(limit=None))
    cmd_ingest_psx(args)
    cmd_ingest_macro(args)
    cmd_ingest_psx_insider(args)
    cmd_ingest_quotes(argparse.Namespace(region=None, limit=None))
    cmd_backfill(argparse.Namespace(region=None, limit=None))
    cmd_ingest_fundamentals(argparse.Namespace(region=None, limit=None))
    cmd_compute(argparse.Namespace(limit=None))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="aerp", description="AERP management CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    def add(name: str, func: Callable, *, region=False, limit=False, providers=False):
        p = sub.add_parser(name)
        if region:
            p.add_argument("--region", default=None, help="us|india|gcc|psx|global")
        if limit:
            p.add_argument("--limit", type=int, default=None)
        if providers:
            p.add_argument("--providers", default=None, help="comma list, e.g. binance,psx")
        p.set_defaults(func=func)
        return p

    add("init-db", cmd_init_db)
    add("seed", cmd_seed)
    add("load-universe", cmd_load_universe, providers=True)
    add("load-us-universe", cmd_load_us_universe, limit=True)
    add("ingest-psx", cmd_ingest_psx)
    add("ingest-macro", cmd_ingest_macro)
    add("ingest-quotes", cmd_ingest_quotes, region=True, limit=True)
    add("backfill", cmd_backfill, region=True, limit=True)
    add("ingest-fundamentals", cmd_ingest_fundamentals, region=True, limit=True)
    add("ingest-insider", cmd_ingest_insider, limit=True)
    add("ingest-psx-insider", cmd_ingest_psx_insider)
    add("ingest-news", cmd_ingest_news, limit=True)
    add("compute", cmd_compute, limit=True)
    add("all", cmd_all)
    return parser


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
