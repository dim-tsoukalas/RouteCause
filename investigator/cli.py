"""Command-line interface.

    investigate <incident.json> [--question ...] [--rfc-dir DIR]
    ask "<question>"            [--rfc-dir DIR]

Mirrors HolmesGPT's two-verb ergonomics (`ask` for free-form doc questions,
`investigate` for a specific incident). Runs fully offline in no-LLM mode;
set INVESTIGATOR_MODEL (+ provider API key) for natural-language narration.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from investigator.engine import InvestigationEngine
from investigator.types import Incident

DEFAULT_RFC_DIR = str(Path(__file__).resolve().parent.parent / "data" / "rfcs")


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="investigator", description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)

    inv = sub.add_parser("investigate", help="investigate an incident JSON file")
    inv.add_argument("incident", help="path to an incident JSON file")
    inv.add_argument("-q", "--question", default="Why did connectivity to this prefix change?")
    inv.add_argument("--rfc-dir", default=DEFAULT_RFC_DIR)

    ask = sub.add_parser("ask", help="ask a question of the RFC corpus (cited)")
    ask.add_argument("question", help="a natural-language question")
    ask.add_argument("--rfc-dir", default=DEFAULT_RFC_DIR)

    return p


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)

    if args.cmd == "investigate":
        incident = Incident.from_json(args.incident)
        engine = InvestigationEngine(rfc_dir=args.rfc_dir)
        report = engine.investigate(incident, args.question)
        print(report.render())
        return 0

    if args.cmd == "ask":
        engine = InvestigationEngine(rfc_dir=args.rfc_dir)
        answer = engine.ask(args.question)
        print(answer.render())
        return 0

    return 1


if __name__ == "__main__":
    sys.exit(main())
