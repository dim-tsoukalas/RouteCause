from datetime import UTC, datetime, timedelta

from investigator.analyzers.route_leak import RouteLeakAnalyzer
from investigator.types import BGPUpdate, Incident

T0 = datetime(2024, 5, 1, 10, 0, tzinfo=UTC)
PREFIX = "203.0.113.0/24"


def _ann(origin, path, peer, offset_s=0):
    return BGPUpdate(T0 + timedelta(seconds=offset_s), "announce", PREFIX, peer,
                     tuple(path), origin, "rrc00")


def test_fires_on_new_shared_transit_as_with_unchanged_origin():
    inc = Incident("t", "", PREFIX, [
        # baseline: two peers, direct to origin, no interior hop
        _ann(64500, [65001, 64500], 65001, offset_s=0),
        _ann(64500, [65002, 64500], 65002, offset_s=60),
        # later: a new interior AS (500) shows up via two distinct peers,
        # same origin as baseline -> the leak signature
        _ann(64500, [65003, 500, 64500], 65003, offset_s=600),
        _ann(64500, [65004, 500, 64500], 65004, offset_s=660),
    ])
    results = RouteLeakAnalyzer().analyze(inc)
    assert len(results) == 1
    assert results[0].severity == "warning"
    assert "500" in " ".join(f.text for f in results[0].findings)


def test_silent_when_origin_also_changes():
    # A changed origin is MOAS's signature, not this analyzer's.
    inc = Incident("t", "", PREFIX, [
        _ann(64500, [65001, 64500], 65001, offset_s=0),
        _ann(64500, [65002, 64500], 65002, offset_s=60),
        _ann(64666, [65003, 500, 64666], 65003, offset_s=600),
        _ann(64666, [65004, 500, 64666], 65004, offset_s=660),
    ])
    assert RouteLeakAnalyzer().analyze(inc) == []


def test_silent_when_no_new_interior_as_appears():
    inc = Incident("t", "", PREFIX, [
        _ann(64500, [65001, 64500], 65001, offset_s=0),
        _ann(64500, [65002, 64500], 65002, offset_s=60),
        _ann(64500, [65003, 64500], 65003, offset_s=600),
        _ann(64500, [65004, 64500], 65004, offset_s=660),
    ])
    assert RouteLeakAnalyzer().analyze(inc) == []


def test_silent_when_new_interior_as_seen_via_only_one_peer():
    inc = Incident("t", "", PREFIX, [
        _ann(64500, [65001, 64500], 65001, offset_s=0),
        _ann(64500, [65002, 64500], 65002, offset_s=60),
        _ann(64500, [65003, 500, 64500], 65003, offset_s=600),
        _ann(64500, [65003, 500, 64500], 65003, offset_s=660),  # same peer again
    ])
    assert RouteLeakAnalyzer().analyze(inc) == []


def test_silent_with_too_few_announcements():
    inc = Incident("t", "", PREFIX, [
        _ann(64500, [65001, 500, 64500], 65001, offset_s=0),
        _ann(64500, [65002, 500, 64500], 65002, offset_s=600),
    ])
    assert RouteLeakAnalyzer().analyze(inc) == []
