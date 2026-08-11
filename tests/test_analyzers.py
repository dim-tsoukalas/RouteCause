from datetime import UTC, datetime, timedelta

from investigator.analyzers import all_analyzers, registered_kinds
from investigator.analyzers.as_path_loop import ASPathLoopAnalyzer
from investigator.analyzers.moas import MOASAnalyzer
from investigator.analyzers.withdrawal_storm import WithdrawalStormAnalyzer
from investigator.types import BGPUpdate, Incident

T0 = datetime(2024, 5, 1, 10, 0, tzinfo=UTC)


def _ann(prefix, origin, path, peer, offset_s=0):
    return BGPUpdate(T0 + timedelta(seconds=offset_s), "announce", prefix, peer,
                     tuple(path), origin, "rrc00")


def _wd(prefix, peer, offset_s=0):
    return BGPUpdate(T0 + timedelta(seconds=offset_s), "withdraw", prefix, peer,
                     (), None, "rrc00")


def test_registry_has_five_analyzers():
    assert set(registered_kinds()) == {
        "MOAS", "WithdrawalStorm", "ASPathLoop", "RouteLeak", "RPKIViolation",
    }
    assert len(all_analyzers()) == 5


def test_moas_flags_multiple_origins():
    inc = Incident("t", "", "203.0.113.0/24", [
        _ann("203.0.113.0/24", 64500, [65001, 64500], 65001),
        _ann("203.0.113.0/24", 64500, [65002, 64500], 65002, 60),
        _ann("203.0.113.0/24", 64666, [65003, 64666], 65003, 120),
    ])
    results = MOASAnalyzer().analyze(inc)
    assert len(results) == 1
    assert results[0].severity == "critical"
    assert "64666" in " ".join(f.text for f in results[0].findings)


def test_moas_silent_on_single_origin():
    inc = Incident("t", "", "203.0.113.0/24", [
        _ann("203.0.113.0/24", 64500, [65001, 64500], 65001),
        _ann("203.0.113.0/24", 64500, [65002, 64500], 65002, 60),
    ])
    assert MOASAnalyzer().analyze(inc) == []


def test_withdrawal_storm_threshold():
    updates = [_wd("203.0.113.0/24", 65000 + i, offset_s=i * 30) for i in range(6)]
    inc = Incident("t", "", "203.0.113.0/24", updates)
    results = WithdrawalStormAnalyzer().analyze(inc)
    assert len(results) == 1
    assert "withdrawals" in results[0].findings[0].text.lower()


def test_withdrawal_storm_below_threshold_is_silent():
    updates = [_wd("203.0.113.0/24", 65000 + i, offset_s=i * 30) for i in range(3)]
    inc = Incident("t", "", "203.0.113.0/24", updates)
    assert WithdrawalStormAnalyzer().analyze(inc) == []


def test_as_path_loop_detected():
    inc = Incident("t", "", "203.0.113.0/24", [
        _ann("203.0.113.0/24", 64500, [65001, 64510, 65001, 64500], 65001),
    ])
    results = ASPathLoopAnalyzer().analyze(inc)
    assert len(results) == 1
    assert "65001" in results[0].findings[0].text


def test_as_path_no_loop_is_silent():
    inc = Incident("t", "", "203.0.113.0/24", [
        _ann("203.0.113.0/24", 64500, [65001, 64510, 64500], 65001),
    ])
    assert ASPathLoopAnalyzer().analyze(inc) == []
