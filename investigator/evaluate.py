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
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from investigator.analyzers import all_analyzers
from investigator.ingest import DEFAULT_CATALOG, incident_output_path, load_catalog
from investigator.types import Incident

# Maps the catalog's small controlled vocabulary to the analyzer kind(s) that
# would count as a hit. An empty set is a deliberate, honest gap: no analyzer
# detects that class of incident today.
LABEL_TO_ANALYZER_KINDS: dict[str, set[str]] = {
    "prefix_hijack": {"MOAS"},
    "moas": {"MOAS"},
    "withdrawal_storm": {"WithdrawalStorm"},
    "as_path_loop": {"ASPathLoop"},
    "route_leak": set(),
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
    args = p.parse_args(argv)

    catalog = load_catalog(Path(args.catalog))
    incidents_dir = Path(args.incidents_dir) if args.incidents_dir else None
    rows = [evaluate_entry(entry, incidents_dir) for entry in catalog]

    print(render_table(rows))
    print()
    print(summarize(rows))
    return 0


if __name__ == "__main__":
    sys.exit(main())
