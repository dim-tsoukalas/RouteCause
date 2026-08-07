"""Command-line interface.

    investigate <incident.json | catalog-name> [--question ...] [--rfc-dir DIR] [--max-search-rounds N] [--toolsets PATH] [--score-citations] [--seek-contradictions]
    ask "<question>"            [--rfc-dir DIR] [--max-search-rounds N] [--toolsets PATH] [--score-citations]

Mirrors HolmesGPT's two-verb ergonomics (`ask` for free-form doc questions,
`investigate` for a specific incident). After `pip install -e .` these are
also console scripts in their own right (`investigate ...` / `ask ...`, see
pyproject.toml's `[project.scripts]` -- each is a thin wrapper that prepends
its verb and calls `main()` below, so `python -m investigator.cli investigate
...` keeps working unchanged too). Runs fully offline in no-LLM mode; set
INVESTIGATOR_MODEL (+ provider API key) for natural-language narration,
including a real multi-round agentic RFC search (see investigator/agent.py) —
offline mode always does exactly one search round. Which analyzers run is
config-driven (investigator/toolsets.toml, see investigator/toolsets.py).
`--score-citations` runs the citation-correctness harness (Phase 3, see
investigator/evaluation/) over the answer -- not applicable in offline mode,
since there's no real narration to check (see the scorecard's own message).
`--seek-contradictions` (investigate only) runs the adversarial-retrieval
harness (Phase 4, see investigator/retrieval/contradiction.py) over each
fired analyzer result, reporting verified counter-evidence per hypothesis
(or an honest "none found" -- never asserted, always entailment-checked),
then ranks the competing hypotheses (Phase 5 ACH, investigator/ach.py) and
either names a leading explanation or explicitly abstains -- a computed
decision from evidence counts, never an LLM judging its own sufficiency.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from investigator.ach import rank_hypotheses
from investigator.engine import InvestigationEngine
from investigator.evaluation.entailment import default_contradiction_checker, default_support_checker
from investigator.evaluation.scorer import score_citations
from investigator.retrieval.contradiction import hypotheses_from_results, seek_contradictions
from investigator.toolsets import DEFAULT_TOOLSETS_PATH, load_citation_eval_config
from investigator.types import Incident

DEFAULT_RFC_DIR = str(Path(__file__).resolve().parent.parent / "data" / "rfcs")
# Not imported from investigator.ingest: that module imports mrtparse at load
# time (an optional extra, see requirements.txt), and the core `investigate`/
# `ask` commands must keep working with no install beyond the standard
# library. So this path is duplicated (not re-exported) from
# investigator.ingest.DATA_DIR -- both must agree on where catalog incident
# JSON lives, but neither should have to import the other's dependencies.
DEFAULT_INCIDENTS_DIR = Path(__file__).resolve().parent.parent / "data" / "incidents"


def _resolve_incident_path(value: str) -> Path:
    """Accepts either a path to an incident JSON file (unchanged, existing
    behavior) or a bare catalog name (e.g. `pakistan-youtube-2008`), which is
    looked up in `data/incidents/` the same way `investigator.ingest` names
    its output files (hyphens -> underscores, see `incident_output_path`).
    This is what makes `investigate pakistan-youtube-2008` work post-install
    instead of requiring the full `data/incidents/pakistan_youtube_2008.json`
    path."""
    direct = Path(value)
    if direct.is_file():
        return direct
    candidate = DEFAULT_INCIDENTS_DIR / f"{value.replace('-', '_')}.json"
    if candidate.is_file():
        return candidate
    raise SystemExit(
        f"no incident found for {value!r} (checked {direct} and {candidate}). "
        f"Pass a path to an incident JSON file, or a catalog name from "
        f"data/incidents/catalog.json -- fetch it first with "
        f"`python -m investigator.ingest catalog {value}` if it isn't ingested yet."
    )


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="investigator", description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)

    inv = sub.add_parser("investigate", help="investigate an incident JSON file")
    inv.add_argument("incident", help="path to an incident JSON file, or a bare catalog "
                                       "name (e.g. pakistan-youtube-2008) resolved against data/incidents/")
    inv.add_argument("-q", "--question", default="Why did connectivity to this prefix change?")
    inv.add_argument("--rfc-dir", default=DEFAULT_RFC_DIR)
    inv.add_argument("--max-search-rounds", type=int, default=3,
                      help="max additional RFC searches the agent loop may request beyond the seed search")
    inv.add_argument("--toolsets", default=str(DEFAULT_TOOLSETS_PATH),
                      help="path to the toolset manifest controlling which analyzers run")
    inv.add_argument("--score-citations", action="store_true",
                      help="run the citation-correctness harness over the explanation")
    inv.add_argument("--seek-contradictions", action="store_true",
                      help="run the adversarial-retrieval harness over each fired analyzer result")

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
    checker_name = load_citation_eval_config(toolsets_path).get("support_checker")
    checker = default_support_checker(checker_name)
    scorecard = score_citations(answer, engine.citations, checker)
    print()
    print(scorecard.render())


def _print_contradictions(report, engine, toolsets_path: str) -> None:
    checker_name = load_citation_eval_config(toolsets_path).get("contradiction_checker")
    checker = default_contradiction_checker(checker_name)
    hypotheses = hypotheses_from_results(report.results)
    print()
    print("Competing considerations (verified counter-evidence, not asserted):")
    if not hypotheses:
        print("  (no analyzer findings to check)")
        return
    checks = []
    for h in hypotheses:
        check = seek_contradictions(h, engine.citations, checker)
        checks.append(check)
        print()
        print(check.render())
    print()
    print(rank_hypotheses(checks).render())


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)

    if args.cmd == "investigate":
        incident = Incident.from_json(_resolve_incident_path(args.incident))
        engine = InvestigationEngine(
            rfc_dir=args.rfc_dir, max_search_rounds=args.max_search_rounds, toolsets_path=args.toolsets
        )
        report = engine.investigate(incident, args.question)
        print(report.render())
        if args.score_citations and report.explanation is not None:
            _print_scorecard(report.explanation, engine, args.toolsets)
        if args.seek_contradictions:
            _print_contradictions(report, engine, args.toolsets)
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


def investigate_main() -> None:
    """Console-script entry point for the `investigate` command (see
    pyproject.toml's `[project.scripts]`) -- just `main()` with the verb
    pinned, so `investigate pakistan-youtube-2008` is `main(["investigate",
    "pakistan-youtube-2008"])` under the hood."""
    sys.exit(main(["investigate", *sys.argv[1:]]))


def ask_main() -> None:
    """Console-script entry point for the `ask` command -- see `investigate_main`."""
    sys.exit(main(["ask", *sys.argv[1:]]))


if __name__ == "__main__":
    sys.exit(main())
