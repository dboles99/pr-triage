"""Command line entry point."""
from __future__ import annotations

import argparse

from . import __version__

COMMANDS = ("review", "calibrate", "study", "label")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="pr-triage", description="Rank an issue's competing pull requests with evidence.")
    p.add_argument("--version", action="store_true", help="print the version and exit")
    sub = p.add_subparsers(dest="cmd")
    for name in COMMANDS:
        sub.add_parser(name)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.version:
        print(f"pr-triage {__version__}")
        return 0
    if not args.cmd:
        build_parser().print_help()
        return 1
    print(f"{args.cmd}: not implemented")
    return 1
