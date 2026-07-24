from __future__ import annotations

import pytest
from app.cli import build_parser


def test_parser_has_all_commands() -> None:
    parser = build_parser()
    # Every documented subcommand should parse and bind a handler.
    for cmd in ["init-db", "seed", "load-universe", "load-us-universe", "ingest-psx",
                "ingest-macro", "ingest-quotes", "backfill", "ingest-fundamentals",
                "ingest-insider", "ingest-psx-insider", "ingest-news",
                "compute", "all"]:
        args = parser.parse_args([cmd])
        assert callable(args.func)


def test_parser_options() -> None:
    parser = build_parser()
    args = parser.parse_args(["compute", "--limit", "5"])
    assert args.limit == 5
    args = parser.parse_args(["ingest-quotes", "--region", "psx"])
    assert args.region == "psx"
    args = parser.parse_args(["load-universe", "--providers", "binance,psx"])
    assert args.providers == "binance,psx"


def test_missing_command_errors() -> None:
    with pytest.raises(SystemExit):
        build_parser().parse_args([])
