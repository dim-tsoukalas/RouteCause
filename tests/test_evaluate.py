import json

from investigator.evaluate import (
    HIT,
    MISS,
    NA,
    evaluate_entry,
    render_table,
    summarize,
    verdict_for_label,
)


def test_verdict_hit():
    assert verdict_for_label("prefix_hijack", {"MOAS"}) == HIT


def test_verdict_miss():
    assert verdict_for_label("prefix_hijack", {"WithdrawalStorm"}) == MISS


def test_verdict_na_for_label_with_no_analyzer():
    assert verdict_for_label("route_leak", {"MOAS", "WithdrawalStorm"}) == NA


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


def test_evaluate_entry_route_leak_is_not_applicable(tmp_path):
    _write_incident(tmp_path / "leak_test.json", "203.0.113.0/24", [64500])
    entry = {"name": "leak-test", "prefixes": ["203.0.113.0/24"], "expected": ["route_leak"]}
    row = evaluate_entry(entry, incidents_dir=tmp_path)
    assert row.verdict_summary() == NA


def test_render_and_summarize_smoke(tmp_path):
    _write_incident(tmp_path / "moas_test.json", "203.0.113.0/24", [64500, 64500, 64666])
    entry = {"name": "moas-test", "prefixes": ["203.0.113.0/24"], "expected": ["prefix_hijack"]}
    row = evaluate_entry(entry, incidents_dir=tmp_path)
    table = render_table([row])
    assert "moas-test" in table
    assert "1/1 correct" in summarize([row])
