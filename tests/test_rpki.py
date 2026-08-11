from datetime import UTC, datetime

import investigator.analyzers.rpki as rpki_analyzer_module
from investigator.analyzers.rpki import RPKIAnalyzer
from investigator.rpki import (
    fetch_for_incident,
    load_cache,
    observed_prefix_origin_pairs,
    save_cache,
)
from investigator.types import BGPUpdate, Incident

T0 = datetime(2024, 5, 1, 10, 0, tzinfo=UTC)


def _ann(prefix, origin, peer):
    return BGPUpdate(T0, "announce", prefix, peer, (peer, origin), origin, "rrc00")


def test_observed_prefix_origin_pairs_ignores_withdrawals_and_missing_origin():
    inc = Incident("t", "", "203.0.113.0/24", [
        _ann("203.0.113.0/24", 64500, 65001),
        _ann("203.0.113.0/24", 64666, 65002),
        BGPUpdate(T0, "withdraw", "203.0.113.0/24", 65001, (), None, "rrc00"),
    ])
    assert observed_prefix_origin_pairs(inc) == {
        ("203.0.113.0/24", 64500),
        ("203.0.113.0/24", 64666),
    }


def test_fetch_for_incident_caches_and_skips_already_cached(monkeypatch):
    inc = Incident("t", "", "203.0.113.0/24", [_ann("203.0.113.0/24", 64500, 65001)])
    calls = []

    def fake_fetch(prefix, asn):
        calls.append((prefix, asn))
        return {"status": "valid", "validating_roas": []}

    monkeypatch.setattr("investigator.rpki.fetch_validation", fake_fetch)
    cache = {}
    fetched = fetch_for_incident(inc, cache)
    assert fetched == 1
    assert calls == [("203.0.113.0/24", 64500)]

    # Second call with the same (now-populated) cache makes no new lookups.
    fetched_again = fetch_for_incident(inc, cache)
    assert fetched_again == 0
    assert calls == [("203.0.113.0/24", 64500)]  # unchanged


def test_fetch_for_incident_caches_an_honest_unknown_on_network_error(monkeypatch):
    inc = Incident("t", "", "203.0.113.0/24", [_ann("203.0.113.0/24", 64500, 65001)])

    def failing_fetch(prefix, asn):
        raise TimeoutError("simulated network failure")

    monkeypatch.setattr("investigator.rpki.fetch_validation", failing_fetch)
    cache = {}
    fetch_for_incident(inc, cache)
    assert cache["203.0.113.0/24|64500"]["status"] == "unknown"
    assert "error" in cache["203.0.113.0/24|64500"]


def test_cache_round_trips_through_disk(tmp_path):
    path = tmp_path / "rpki_cache.json"
    save_cache({"1.2.3.0/24|64500": {"status": "valid", "validating_roas": []}}, path)
    assert load_cache(path) == {"1.2.3.0/24|64500": {"status": "valid", "validating_roas": []}}


def test_load_cache_missing_file_returns_empty_dict(tmp_path):
    assert load_cache(tmp_path / "does_not_exist.json") == {}


def _set_cache(monkeypatch, tmp_path, data: dict):
    path = tmp_path / "rpki_cache.json"
    save_cache(data, path)
    monkeypatch.setattr(rpki_analyzer_module, "CACHE_PATH", path)


def test_rpki_analyzer_flags_invalid_asn(monkeypatch, tmp_path):
    inc = Incident("t", "", "203.0.113.0/24", [_ann("203.0.113.0/24", 64500, 65001)])
    _set_cache(monkeypatch, tmp_path, {
        "203.0.113.0/24|64500": {"status": "invalid_asn", "validating_roas": [{"origin": "64999"}]},
    })
    results = RPKIAnalyzer().analyze(inc)
    assert len(results) == 1
    assert results[0].kind == "RPKIViolation"
    assert "AS64500" in results[0].findings[0].text
    assert results[0].evidence  # the announce evidence_ref was collected


def test_rpki_analyzer_silent_when_all_valid(monkeypatch, tmp_path):
    inc = Incident("t", "", "203.0.113.0/24", [_ann("203.0.113.0/24", 64500, 65001)])
    _set_cache(monkeypatch, tmp_path, {
        "203.0.113.0/24|64500": {"status": "valid", "validating_roas": [{"origin": "64500"}]},
    })
    assert RPKIAnalyzer().analyze(inc) == []


def test_rpki_analyzer_silent_when_nothing_cached(monkeypatch, tmp_path):
    # Not fetched yet -- no claim made either way, not a crash.
    inc = Incident("t", "", "203.0.113.0/24", [_ann("203.0.113.0/24", 64500, 65001)])
    _set_cache(monkeypatch, tmp_path, {})
    assert RPKIAnalyzer().analyze(inc) == []
