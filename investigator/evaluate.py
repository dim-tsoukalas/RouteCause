"""Detection-accuracy evaluation harness.

For each incident in `data/incidents/catalog.json`, loads the pre-ingested
incident JSON (produced by `investigator.ingest` - no network here, this stays
offline and fast like the rest of the test suite), runs every registered
analyzer over it, and compares what fired against the catalog's `expected`
labels.

Deliberately not named `evaluation/` - that name is reserved in
docs/design.md for the future citation-*correctness* harness (Phase 3), a
different concern from detection accuracy.

    PYTHONPATH=. python -m investigator.evaluate
    PYTHONPATH=. python -m investigator.evaluate --ach

`--ach` additionally measures Phase 5's competing-hypothesis (ACH) reasoning
against the same real catalog + ground truth: for each incident, ranks its
fired analyzer results as competing hypotheses (investigator/ach.py) and
checks whether the leading (non-abstained) hypothesis actually matches the
catalog's expected label -- the false-assertion rate the Phase 5 plan calls
for, measured against real data rather than a synthetic held-out case. Only
this mode loads the RFC corpus / builds a CitationEngine; the default path's
cost and behavior are unchanged.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from investigator.ach import ACHMatrix, build_ach_matrix
from investigator.analyzers import all_analyzers
from investigator.evaluation.entailment import EntailmentChecker, default_checker
from investigator.ingest import DEFAULT_CATALOG, incident_output_path, load_catalog
from investigator.retrieval.citations import CitationEngine
from investigator.retrieval.contradiction import hypotheses_from_results
from investigator.retrieval.corpus import load_corpus
from investigator.toolsets import DEFAULT_TOOLSETS_PATH, load_citation_eval_config
from investigator.types import Incident, Result

DEFAULT_RFC_DIR = str(Path(__file__).resolve().parent.parent / "data" / "rfcs")

# Maps the catalog's small controlled vocabulary to the analyzer kind(s) that
# would count as a hit. An empty set is a deliberate, honest gap: no analyzer
# detects that class of incident today.
LABEL_TO_ANALYZER_KINDS: dict[str, set[str]] = {
    "prefix_hijack": {"MOAS"},
    "moas": {"MOAS"},
    "withdrawal_storm": {"WithdrawalStorm"},
    "as_path_loop": {"ASPathLoop"},
    # RouteLeak (investigator/analyzers/route_leak.py) is a heuristic, not
    # policy-violation proof (no AS-relationship data available) -- see its
    # docstring. Still a real analyzer now, so this is no longer an
    # unconditional N/A gap.
    "route_leak": {"RouteLeak"},
}

HIT, MISS, NA = "HIT", "MISS", "N/A"


def verdict_for_label(label: str, detected_kinds: set[str]) -> str:
    mapped = LABEL_TO_ANALYZER_KINDS.get(label)
    if not mapped:
        return NA  # unrecognized label, or a known label with no analyzer yet
    return HIT if detected_kinds & mapped else MISS


def detected_kinds_for_incident(incident: Incident) -> set[str]:
    kinds: set[str] = set()
    for analyzer in all_analyzers():
        for result in analyzer.analyze(incident):
            if not result.is_empty():
                kinds.add(result.kind)
    return kinds


def fired_results_for_incident(incident: Incident) -> list[Result]:
    """Sibling of `detected_kinds_for_incident` that keeps the full `Result`
    (not just its kind) -- needed for ACH, since `hypotheses_from_results`
    needs `Result.details` to build a human-readable hypothesis statement."""
    return [
        result
        for analyzer in all_analyzers()
        for result in analyzer.analyze(incident)
        if not result.is_empty()
    ]


class EvalRow:
    def __init__(self, name: str, expected: list[str], detected: set[str],
                 verdicts: list[str], missing_files: list[str]):
        self.name = name
        self.expected = expected
        self.detected = detected
        self.verdicts = verdicts
        self.missing_files = missing_files

    def verdict_summary(self) -> str:
        if self.missing_files:
            return "missing"
        if not self.verdicts or all(v == NA for v in self.verdicts):
            return NA
        return MISS if any(v == MISS for v in self.verdicts) else HIT


def evaluate_entry(entry: dict, incidents_dir: Path | None = None) -> EvalRow:
    prefixes = entry["prefixes"]
    single = len(prefixes) == 1
    detected: set[str] = set()
    missing_files: list[str] = []

    for prefix in prefixes:
        path = incident_output_path(entry["name"], prefix, single=single)
        if incidents_dir is not None:
            path = incidents_dir / path.name
        if not path.exists():
            missing_files.append(str(path))
            continue
        incident = Incident.from_json(path)
        detected |= detected_kinds_for_incident(incident)

    expected = entry.get("expected", [])
    verdicts = [verdict_for_label(label, detected) for label in expected]
    return EvalRow(entry["name"], expected, detected, verdicts, missing_files)


def _fired_results_for_entry(entry: dict, incidents_dir: Path | None) -> tuple[list[Result], list[str]]:
    """Aggregated across all of a (possibly multi-prefix) entry's incident
    files, deduped by analyzer kind (first fired Result per kind wins) so a
    multi-prefix entry doesn't produce several near-duplicate hypotheses of
    the same kind. Mirrors evaluate_entry's own multi-prefix aggregation."""
    prefixes = entry["prefixes"]
    single = len(prefixes) == 1
    by_kind: dict[str, Result] = {}
    missing_files: list[str] = []
    for prefix in prefixes:
        path = incident_output_path(entry["name"], prefix, single=single)
        if incidents_dir is not None:
            path = incidents_dir / path.name
        if not path.exists():
            missing_files.append(str(path))
            continue
        incident = Incident.from_json(path)
        for result in fired_results_for_incident(incident):
            by_kind.setdefault(result.kind, result)
    return list(by_kind.values()), missing_files


def _leading_kind_matches_expected(leading_kind: str, expected_labels: list[str]) -> bool:
    return any(leading_kind in LABEL_TO_ANALYZER_KINDS.get(label, set()) for label in expected_labels)


class ACHEvalRow:
    def __init__(self, name: str, expected: list[str], matrix: ACHMatrix | None, missing_files: list[str]):
        self.name = name
        self.expected = expected
        self.matrix = matrix
        self.missing_files = missing_files

    def outcome(self) -> str:
        """One of: 'missing', 'abstained', 'correct', 'false'. A partially-
        missing multi-prefix entry that still fired on its other prefixes is
        scored from what it did fire on, not counted as fully missing."""
        if self.missing_files and self.matrix is None:
            return "missing"
        if self.matrix is None or self.matrix.abstained or self.matrix.leading is None:
            return "abstained"
        if _leading_kind_matches_expected(self.matrix.leading.hypothesis.kind, self.expected):
            return "correct"
        return "false"


def evaluate_entry_ach(
    entry: dict, incidents_dir: Path | None, citations: CitationEngine, checker: EntailmentChecker
) -> ACHEvalRow:
    results, missing_files = _fired_results_for_entry(entry, incidents_dir)
    expected = entry.get("expected", [])
    if not results:
        return ACHEvalRow(entry["name"], expected, None, missing_files)
    hypotheses = hypotheses_from_results(results)
    matrix = build_ach_matrix(hypotheses, citations, checker)
    return ACHEvalRow(entry["name"], expected, matrix, missing_files)


def render_ach_table(rows: list[ACHEvalRow]) -> str:
    lines = ["| Incident | Expected | ACH Verdict | Outcome |", "|---|---|---|---|"]
    for row in rows:
        if row.missing_files and row.matrix is None:
            lines.append(f"| {row.name} | {', '.join(row.expected)} | _(not ingested)_ | missing |")
            continue
        if row.matrix is None or row.matrix.abstained:
            reason = row.matrix.abstain_reason if row.matrix else "no analyzer findings fired"
            verdict_str = f"ABSTAIN ({reason})"
        else:
            verdict_str = f"[{row.matrix.leading.hypothesis.kind}]"
        lines.append(f"| {row.name} | {', '.join(row.expected)} | {verdict_str} | {row.outcome()} |")
    return "\n".join(lines)


def summarize_ach(rows: list[ACHEvalRow]) -> str:
    scored = [r for r in rows if not (r.missing_files and r.matrix is None)]
    abstained = sum(1 for r in scored if r.outcome() == "abstained")
    correct = sum(1 for r in scored if r.outcome() == "correct")
    false = sum(1 for r in scored if r.outcome() == "false")
    total_assertions = correct + false
    rate = f"{false}/{total_assertions} ({false / total_assertions:.0%})" if total_assertions else "n/a (no assertions made)"
    missing = sum(1 for r in rows if r.missing_files and r.matrix is None)
    parts = [f"false-assertion rate: {rate}", f"{correct} correct assertion(s)", f"{abstained} abstained"]
    if missing:
        parts.append(f"{missing} not yet ingested")
    return ", ".join(parts)


def render_table(rows: list[EvalRow]) -> str:
    lines = ["| Incident | Expected | Detected | Verdict |", "|---|---|---|---|"]
    for row in rows:
        if row.missing_files:
            lines.append(
                f"| {row.name} | {', '.join(row.expected)} | _(not ingested - run "
                f"`python -m investigator.ingest catalog {row.name}`)_ | missing |"
            )
            continue
        detected_str = ", ".join(sorted(row.detected)) or "(none)"
        verdict_str = ", ".join(row.verdicts) or NA
        lines.append(f"| {row.name} | {', '.join(row.expected)} | {detected_str} | {verdict_str} |")
    return "\n".join(lines)


def summarize(rows: list[EvalRow]) -> str:
    scored = [r for r in rows if r.verdict_summary() in (HIT, MISS)]
    correct = sum(1 for r in scored if r.verdict_summary() == HIT)
    na = sum(1 for r in rows if r.verdict_summary() == NA)
    missing = sum(1 for r in rows if r.missing_files)
    parts = [f"{correct}/{len(scored)} correct"]
    if na:
        parts.append(f"{na} not applicable (no analyzer for that class yet)")
    if missing:
        parts.append(f"{missing} not yet ingested")
    return ", ".join(parts)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--catalog", default=str(DEFAULT_CATALOG))
    p.add_argument("--incidents-dir", default=None,
                    help="override where incident JSON files are looked up (default: data/incidents)")
    p.add_argument("--ach", action="store_true",
                    help="also measure Phase 5's competing-hypothesis false-assertion rate")
    p.add_argument("--rfc-dir", default=DEFAULT_RFC_DIR, help="only used with --ach")
    p.add_argument("--toolsets", default=str(DEFAULT_TOOLSETS_PATH), help="only used with --ach")
    args = p.parse_args(argv)

    catalog = load_catalog(Path(args.catalog))
    incidents_dir = Path(args.incidents_dir) if args.incidents_dir else None
    rows = [evaluate_entry(entry, incidents_dir) for entry in catalog]

    print(render_table(rows))
    print()
    print(summarize(rows))

    if args.ach:
        citations = CitationEngine(load_corpus(args.rfc_dir))
        checker_name = load_citation_eval_config(args.toolsets).get("checker")
        checker = default_checker(checker_name)
        ach_rows = [evaluate_entry_ach(entry, incidents_dir, citations, checker) for entry in catalog]
        print()
        print(render_ach_table(ach_rows))
        print()
        print(summarize_ach(ach_rows))

    return 0


if __name__ == "__main__":
    sys.exit(main())
