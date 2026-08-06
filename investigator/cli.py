"""Command-line interface.

    investigate <incident.json> [--question ...] [--rfc-dir DIR] [--max-search-rounds N] [--toolsets PATH] [--score-citations]
    ask "<question>"            [--rfc-dir DIR] [--max-search-rounds N] [--toolsets PATH] [--score-citations]

Mirrors HolmesGPT's two-verb ergonomics (`ask` for free-form doc questions,
`investigate` for a specific incident). Runs fully offline in no-LLM mode;
set INVESTIGATOR_MODEL (+ provider API key) for natural-language narration,
including a real multi-round agentic RFC search (see investigator/agent.py) —
offline mode always does exactly one search round. Which analyzers run is
config-driven (investigator/toolsets.toml, see investigator/toolsets.py).
`--score-citations` runs the citation-correctness harness (Phase 3, see
investigator/evaluation/) over the answer -- not applicable in offline mode,
since there's no real narration to check (see the scorecard's own message).
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from investigator.engine import InvestigationEngine
from investigator.evaluation.entailment import default_checker
from investigator.evaluation.scorer import score_citations
from investigator.toolsets import DEFAULT_TOOLSETS_PATH, load_citation_eval_config
from investigator.types import Incident

DEFAULT_RFC_DIR = str(Path(__file__).resolve().parent.parent / "data" / "rfcs")


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="investigator", description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)

    inv = sub.add_parser("investigate", help="investigate an incident JSON file")
    inv.add_argument("incident", help="path to an incident JSON file")
    inv.add_argument("-q", "--question", default="Why did connectivity to this prefix change?")
    inv.add_argument("--rfc-dir", default=DEFAULT_RFC_DIR)
    inv.add_argument("--max-search-rounds", type=int, default=3,
                      help="max additional RFC searches the agent loop may request beyond the seed search")
    inv.add_argument("--toolsets", default=str(DEFAULT_TOOLSETS_PATH),
                      help="path to the toolset manifest controlling which analyzers run")
    inv.add_argument("--score-citations", action="store_true",
                      help="run the citation-correctness harness over the explanation")

    ask = sub.add_parser("ask", help="ask a question of the RFC corpus (cited)")
    ask.add_argument("question", help="a natural-language question")
    ask.add_argument("--rfc-dir", default=DEFAULT_RFC_DIR)
    ask.add_argument("--max-search-rounds", type=int, default=3,
                      help="max additional RFC searches the agent loop may request beyond the seed search")
    ask.add_argument("--toolsets", default=str(DEFAULT_TOOLSETS_PATH),
                      help="path to the toolset manifest (only its [rfc_search]/[citation_eval] tables matter for `ask`)")
    ask.add_argument("--score-citations", action="store_true",
                      help="run the citation-correctness harness over the answer")

    return p


def _print_scorecard(answer, engine, toolsets_path: str) -> None:
    checker_name = load_citation_eval_config(toolsets_path).get("checker")
    checker = default_checker(checker_name)
    scorecard = score_citations(answer, engine.citations, checker)
    print()
    print(scorecard.render())


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)

    if args.cmd == "investigate":
        incident = Incident.from_json(args.incident)
        engine = InvestigationEngine(
            rfc_dir=args.rfc_dir, max_search_rounds=args.max_search_rounds, toolsets_path=args.toolsets
        )
        report = engine.investigate(incident, args.question)
        print(report.render())
        if args.score_citations and report.explanation is not None:
            _print_scorecard(report.explanation, engine, args.toolsets)
        return 0

    if args.cmd == "ask":
        engine = InvestigationEngine(
            rfc_dir=args.rfc_dir, max_search_rounds=args.max_search_rounds, toolsets_path=args.toolsets
        )
        answer = engine.ask(args.question)
        print(answer.render())
        if args.score_citations:
            _print_scorecard(answer, engine, args.toolsets)
        return 0

    return 1


if __name__ == "__main__":
    sys.exit(main())
