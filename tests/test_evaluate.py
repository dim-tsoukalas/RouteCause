import json

from investigator.evaluate import (
    HIT,
    MISS,
    NA,
    evaluate_entry,
    evaluate_entry_ach,
    render_ach_table,
    render_table,
    summarize,
    summarize_ach,
    verdict_for_label,
)
from investigator.evaluation.entailment import LexicalOverlapChecker
from investigator.retrieval.citations import CitationEngine
from investigator.retrieval.corpus import Chunk


def test_verdict_hit():
    assert verdict_for_label("prefix_hijack", {"MOAS"}) == HIT


def test_verdict_miss():
    assert verdict_for_label("prefix_hijack", {"WithdrawalStorm"}) == MISS


def test_verdict_hit_for_route_leak_when_detected():
    # Phase 2: route_leak is a real, mapped label now (RouteLeakAnalyzer
    # exists) -- no longer an unconditional N/A gap.
    assert verdict_for_label("route_leak", {"RouteLeak"}) == HIT


def test_verdict_miss_for_route_leak_when_not_detected():
    assert verdict_for_label("route_leak", {"MOAS", "WithdrawalStorm"}) == MISS


def test_verdict_na_for_unknown_label():
    assert verdict_for_label("something_unmapped", {"MOAS"}) == NA


def _write_incident(path, prefix, origins):
    updates = [
        {
            "timestamp": f"2024-05-01T10:{i:02d}:00Z",
            "kind": "announce",
            "prefix": prefix,
            "peer_asn": 65000 + i,
            "as_path": [65000 + i, origin],
            "origin_asn": origin,
            "collector": "rrc00",
        }
        for i, origin in enumerate(origins)
    ]
    path.write_text(json.dumps({
        "incident_id": "t", "description": "", "prefix": prefix, "updates": updates,
    }))


def test_evaluate_entry_hit(tmp_path):
    _write_incident(tmp_path / "moas_test.json", "203.0.113.0/24", [64500, 64500, 64666])
    entry = {"name": "moas-test", "prefixes": ["203.0.113.0/24"], "expected": ["prefix_hijack"]}
    row = evaluate_entry(entry, incidents_dir=tmp_path)
    assert row.verdict_summary() == HIT
    assert row.detected == {"MOAS"}


def test_evaluate_entry_missing_file(tmp_path):
    entry = {"name": "not-ingested-yet", "prefixes": ["1.2.3.0/24"], "expected": ["prefix_hijack"]}
    row = evaluate_entry(entry, incidents_dir=tmp_path)
    assert row.missing_files
    assert row.verdict_summary() == "missing"
    assert "missing" in render_table([row])


def test_evaluate_entry_route_leak_miss_when_no_leak_pattern(tmp_path):
    # Too little/no leak-shaped evidence in this fixture -> RouteLeakAnalyzer
    # stays silent -> MISS (a real verdict now, not an automatic N/A).
    _write_incident(tmp_path / "leak_test.json", "203.0.113.0/24", [64500])
    entry = {"name": "leak-test", "prefixes": ["203.0.113.0/24"], "expected": ["route_leak"]}
    row = evaluate_entry(entry, incidents_dir=tmp_path)
    assert row.verdict_summary() == MISS


def _write_leak_shaped_incident(path, prefix):
    # Mirrors tests/test_route_leak.py's HIT scenario: a new interior AS
    # appears via two distinct peers partway through, origin unchanged.
    updates = [
        {"timestamp": "2024-05-01T10:00:00Z", "kind": "announce", "prefix": prefix,
         "peer_asn": 65001, "as_path": [65001, 64500], "origin_asn": 64500, "collector": "rrc00"},
        {"timestamp": "2024-05-01T10:01:00Z", "kind": "announce", "prefix": prefix,
         "peer_asn": 65002, "as_path": [65002, 64500], "origin_asn": 64500, "collector": "rrc00"},
        {"timestamp": "2024-05-01T10:10:00Z", "kind": "announce", "prefix": prefix,
         "peer_asn": 65003, "as_path": [65003, 500, 64500], "origin_asn": 64500, "collector": "rrc00"},
        {"timestamp": "2024-05-01T10:11:00Z", "kind": "announce", "prefix": prefix,
         "peer_asn": 65004, "as_path": [65004, 500, 64500], "origin_asn": 64500, "collector": "rrc00"},
    ]
    path.write_text(json.dumps({
        "incident_id": "t", "description": "", "prefix": prefix, "updates": updates,
    }))


def test_evaluate_entry_route_leak_hit_when_leak_pattern_present(tmp_path):
    _write_leak_shaped_incident(tmp_path / "leak_hit_test.json", "203.0.113.0/24")
    entry = {"name": "leak-hit-test", "prefixes": ["203.0.113.0/24"], "expected": ["route_leak"]}
    row = evaluate_entry(entry, incidents_dir=tmp_path)
    assert row.verdict_summary() == HIT
    assert row.detected == {"RouteLeak"}


def test_render_and_summarize_smoke(tmp_path):
    _write_incident(tmp_path / "moas_test.json", "203.0.113.0/24", [64500, 64500, 64666])
    entry = {"name": "moas-test", "prefixes": ["203.0.113.0/24"], "expected": ["prefix_hijack"]}
    row = evaluate_entry(entry, incidents_dir=tmp_path)
    table = render_table([row])
    assert "moas-test" in table
    assert "1/1 correct" in summarize([row])


# --- Phase 5: ACH false-assertion-rate measurement -------------------------

def _empty_citations():
    return CitationEngine([])  # no chunks -> seek_contradictions finds nothing either way


def _supportive_citations():
    # Real, non-empty corpus whose text closely overlaps the exact analyzer
    # Result.details phrasing, so LexicalOverlapChecker genuinely finds
    # supporting evidence rather than the zero-signal case
    # test_ach.py's ranking-rule fix (see investigator/ach.py) now correctly
    # abstains on.
    return CitationEngine([
        Chunk("MOAS-DOC", "2 origin ASNs observed for a single prefix is the definition of a "
                          "MOAS condition and a strong hijack indicator."),
        Chunk("LEAK-DOC", "1 new transit AS(es) appeared mid-window across >= 2 peers each, "
                          "origin unchanged, is the definition of a route leak."),
    ], top_k=6, min_score=0.1)


def test_evaluate_entry_ach_correct_assertion(tmp_path):
    _write_incident(tmp_path / "moas_test.json", "203.0.113.0/24", [64500, 64500, 64666])
    entry = {"name": "moas-test", "prefixes": ["203.0.113.0/24"], "expected": ["prefix_hijack"]}
    row = evaluate_entry_ach(entry, tmp_path, _supportive_citations(), LexicalOverlapChecker())
    assert row.outcome() == "correct"
    assert row.matrix.leading.hypothesis.kind == "MOAS"


def test_evaluate_entry_ach_false_assertion(tmp_path):
    # RouteLeak fires, but the entry claims prefix_hijack -> a false assertion.
    _write_leak_shaped_incident(tmp_path / "leak_test.json", "203.0.113.0/24")
    entry = {"name": "leak-test", "prefixes": ["203.0.113.0/24"], "expected": ["prefix_hijack"]}
    row = evaluate_entry_ach(entry, tmp_path, _supportive_citations(), LexicalOverlapChecker())
    assert row.outcome() == "false"


def test_evaluate_entry_ach_abstains_with_no_fired_results(tmp_path):
    _write_incident(tmp_path / "quiet_test.json", "203.0.113.0/24", [64500])
    entry = {"name": "quiet-test", "prefixes": ["203.0.113.0/24"], "expected": ["prefix_hijack"]}
    row = evaluate_entry_ach(entry, tmp_path, _empty_citations(), LexicalOverlapChecker())
    assert row.outcome() == "abstained"


def test_evaluate_entry_ach_abstains_when_no_supporting_evidence_found(tmp_path):
    # The bug this project actually found: an empty/irrelevant corpus must
    # not let a hypothesis "win" purely by avoiding contradiction.
    _write_incident(tmp_path / "moas_test.json", "203.0.113.0/24", [64500, 64500, 64666])
    entry = {"name": "moas-test", "prefixes": ["203.0.113.0/24"], "expected": ["prefix_hijack"]}
    row = evaluate_entry_ach(entry, tmp_path, _empty_citations(), LexicalOverlapChecker())
    assert row.outcome() == "abstained"


def test_summarize_ach_false_assertion_rate(tmp_path):
    _write_incident(tmp_path / "moas_test.json", "203.0.113.0/24", [64500, 64500, 64666])
    _write_leak_shaped_incident(tmp_path / "leak_test.json", "198.51.100.0/24")
    correct_entry = {"name": "moas-test", "prefixes": ["203.0.113.0/24"], "expected": ["prefix_hijack"]}
    false_entry = {"name": "leak-test", "prefixes": ["198.51.100.0/24"], "expected": ["prefix_hijack"]}
    checker = LexicalOverlapChecker()
    citations = _supportive_citations()
    rows = [
        evaluate_entry_ach(correct_entry, tmp_path, citations, checker),
        evaluate_entry_ach(false_entry, tmp_path, citations, checker),
    ]
    summary = summarize_ach(rows)
    assert "false-assertion rate: 1/2 (50%)" in summary
    table = render_ach_table(rows)
    assert "moas-test" in table and "leak-test" in table
