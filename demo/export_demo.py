"""Export real investigation output to demo_data.json for the static demo.

Runs the ACTUAL engine (deterministic analyzers + agentic RFC retrieval +
adversarial contradiction search + ACH ranking) over catalog incidents and
serializes the structured result. Nothing here is fabricated: every field is
computed by the real pipeline, the same code paths the CLI uses.

Usage (from the repo root):
    python demo/export_demo.py pakistan-youtube-2008 indosat-2014 \
        google-japan-leak-2017 twitter-rtcomm-2022 > demo/demo_data.json
"""
from __future__ import annotations
import json, sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
RFC_DIR = str(REPO / "data" / "rfcs")
INCIDENTS = REPO / "data" / "incidents"
sys.path.insert(0, str(REPO))

from investigator.ach import rank_hypotheses
from investigator.engine import InvestigationEngine
from investigator.evaluation.entailment import default_contradiction_checker
from investigator.retrieval.contradiction import hypotheses_from_results, seek_contradictions
from investigator.toolsets import DEFAULT_TOOLSETS_PATH, load_citation_eval_config
from investigator.types import Incident

DEFAULT_INCIDENTS = [
    "pakistan-youtube-2008", "indosat-2014",
    "google-japan-leak-2017", "twitter-rtcomm-2022",
]


def sd(s):
    return {"n": s.n, "source_id": s.source_id, "text": s.text}


def export_incident(name: str) -> dict:
    incident = Incident.from_json(str(INCIDENTS / f"{name.replace('-', '_')}.json"))
    engine = InvestigationEngine(rfc_dir=RFC_DIR, toolsets_path=DEFAULT_TOOLSETS_PATH)
    report = engine.investigate(incident, "Why did connectivity to this prefix change?")

    observations = []
    for r in report.results:
        if r.is_empty():
            continue
        observations.append({
            "kind": r.kind, "name": r.name, "severity": r.severity,
            "findings": [{"text": f.text, "rfc_hint": f.rfc_hint} for f in r.findings],
            "evidence": r.evidence[:6], "evidence_extra": max(0, len(r.evidence) - 6),
        })

    checker_name = load_citation_eval_config(DEFAULT_TOOLSETS_PATH).get("contradiction_checker")
    checker = default_contradiction_checker(checker_name)
    checks, hyp_out = [], []
    for h in hypotheses_from_results(report.results):
        c = seek_contradictions(h, engine.citations, checker)
        checks.append(c)
        hyp_out.append({
            "kind": c.hypothesis.kind, "statement": c.hypothesis.statement,
            "supporting": [sd(s) for s in c.supporting],
            "topically_relevant": [sd(s) for s in c.topically_relevant],
            "contradicting": [sd(s) for s in c.contradicting],
            "checker_name": c.checker_name,
        })

    matrix = rank_hypotheses(checks) if checks else None
    verdict = None
    if matrix is not None:
        verdict = {
            "abstained": matrix.abstained, "abstain_reason": matrix.abstain_reason,
            "scores": [{
                "kind": s.hypothesis.kind, "statement": s.hypothesis.statement,
                "supporting_count": s.supporting_count, "relevant_count": s.relevant_count,
                "contradicting_count": s.contradicting_count,
            } for s in matrix.scores],
            "leading": None if matrix.leading is None else {
                "kind": matrix.leading.hypothesis.kind, "statement": matrix.leading.hypothesis.statement,
                "supporting_count": matrix.leading.supporting_count,
                "relevant_count": matrix.leading.relevant_count,
                "contradicting_count": matrix.leading.contradicting_count,
            },
        }

    return {
        "incident_id": incident.incident_id, "description": incident.description,
        "prefix": incident.prefix, "source": incident.source,
        "ground_truth": incident.ground_truth, "update_count": len(incident.updates),
        "observations": observations, "hypotheses": hyp_out, "verdict": verdict,
    }


if __name__ == "__main__":
    names = sys.argv[1:] or DEFAULT_INCIDENTS
    print(json.dumps([export_incident(n) for n in names], indent=2))
