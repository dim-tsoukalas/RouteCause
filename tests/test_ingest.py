from datetime import datetime, timezone

from investigator.ingest import extract_rib_entries, extract_updates, incident_output_path

TS = {1561372200: "2019-06-24 12:30:00"}  # epoch is authoritative; mrtparse's label string is local-time


def _announce_record(nlri_prefixes, as_path=("396503", "53356", "6939")):
    return {
        "timestamp": TS,
        "afi": {1: "IPv4"},
        "peer_as": "396503",
        "bgp_message": {
            "type": {2: "UPDATE"},
            "withdrawn_routes": [],
            "path_attributes": [
                {"flag": 64, "type": {1: "ORIGIN"}, "length": 1, "value": {0: "IGP"}},
                {
                    "flag": 64,
                    "type": {2: "AS_PATH"},
                    "value": [{"type": {2: "AS_SEQUENCE"}, "value": list(as_path)}],
                },
            ],
            "nlri": [{"length": length, "prefix": prefix} for prefix, length in nlri_prefixes],
        },
    }


def _withdraw_record(withdrawn):
    return {
        "timestamp": TS,
        "afi": {1: "IPv4"},
        "peer_as": "396503",
        "bgp_message": {
            "type": {2: "UPDATE"},
            "withdrawn_routes": [{"length": length, "prefix": prefix} for prefix, length in withdrawn],
            "path_attributes": [],
            "nlri": [],
        },
    }


def test_extract_announce_filters_to_target_prefix():
    record = _announce_record([("104.16.0.0", 12), ("8.8.8.0", 24)])
    updates = extract_updates(record, {"104.16.0.0/12"}, "rrc00")
    assert len(updates) == 1
    u = updates[0]
    assert u.kind == "announce"
    assert u.prefix == "104.16.0.0/12"
    assert u.peer_asn == 396503
    assert u.as_path == (396503, 53356, 6939)
    assert u.origin_asn == 6939
    assert u.collector == "rrc00"
    assert u.timestamp == datetime(2019, 6, 24, 10, 30, tzinfo=timezone.utc)


def test_extract_announce_no_match_is_empty():
    record = _announce_record([("8.8.8.0", 24)])
    assert extract_updates(record, {"104.16.0.0/12"}, "rrc00") == []


def test_extract_matches_multiple_target_prefixes_in_one_pass():
    record = _announce_record([("104.16.0.0", 12), ("203.0.113.0", 24), ("8.8.8.0", 24)])
    updates = extract_updates(record, {"104.16.0.0/12", "203.0.113.0/24"}, "rrc00")
    assert {u.prefix for u in updates} == {"104.16.0.0/12", "203.0.113.0/24"}


def test_extract_withdraw_filters_to_target_prefix():
    record = _withdraw_record([("104.16.0.0", 12), ("8.8.8.0", 24)])
    updates = extract_updates(record, {"104.16.0.0/12"}, "rrc00")
    assert len(updates) == 1
    assert updates[0].kind == "withdraw"
    assert updates[0].as_path == ()
    assert updates[0].origin_asn is None


def test_extract_ignores_non_ipv4():
    record = _announce_record([("104.16.0.0", 12)])
    record["afi"] = {2: "IPv6"}
    assert extract_updates(record, {"104.16.0.0/12"}, "rrc00") == []


def test_extract_ignores_non_update_messages():
    record = {
        "timestamp": TS,
        "afi": {1: "IPv4"},
        "peer_as": "396503",
        "bgp_message": {"type": {4: "KEEPALIVE"}},
    }
    assert extract_updates(record, {"104.16.0.0/12"}, "rrc00") == []


def _rib_record(prefix, length, entries):
    return {
        "type": {13: "TABLE_DUMP_V2"},
        "subtype": {2: "RIB_IPV4_UNICAST"},
        "prefix": prefix,
        "length": length,
        "rib_entries": [
            {
                "peer_index": peer_index,
                "path_attributes": [
                    {"flag": 64, "type": {1: "ORIGIN"}, "length": 1, "value": {0: "IGP"}},
                    {
                        "flag": 64,
                        "type": {2: "AS_PATH"},
                        "value": [{"type": {2: "AS_SEQUENCE"}, "value": list(as_path)}],
                    },
                ],
            }
            for peer_index, as_path in entries
        ],
    }


AT = datetime(2018, 4, 24, 11, 0, tzinfo=timezone.utc)


def test_extract_rib_entries_produces_baseline_announce():
    record = _rib_record("205.251.192.0", 24, [(0, ("45896", "3356", "16509"))])
    updates = extract_rib_entries(record, {"205.251.192.0/24"}, {0: 45896}, AT, "rrc00")
    assert len(updates) == 1
    u = updates[0]
    assert u.kind == "announce"
    assert u.prefix == "205.251.192.0/24"
    assert u.peer_asn == 45896
    assert u.as_path == (45896, 3356, 16509)
    assert u.origin_asn == 16509
    assert u.timestamp == AT


def test_extract_rib_entries_no_match_is_empty():
    record = _rib_record("8.8.8.0", 24, [(0, ("45896", "15169"))])
    assert extract_rib_entries(record, {"205.251.192.0/24"}, {0: 45896}, AT, "rrc00") == []


def test_extract_rib_entries_ignores_non_rib_records():
    record = {"type": {13: "TABLE_DUMP_V2"}, "subtype": {1: "PEER_INDEX_TABLE"}, "peer_entries": []}
    assert extract_rib_entries(record, {"205.251.192.0/24"}, {}, AT, "rrc00") == []


def test_extract_rib_entries_multiple_peers_same_prefix():
    record = _rib_record("205.251.192.0", 24, [
        (0, ("45896", "3356", "16509")),
        (1, ("7018", "16509")),
    ])
    updates = extract_rib_entries(record, {"205.251.192.0/24"}, {0: 45896, 1: 7018}, AT, "rrc00")
    assert len(updates) == 2
    assert {u.peer_asn for u in updates} == {45896, 7018}
    assert all(u.origin_asn == 16509 for u in updates)


def test_incident_output_path_single_prefix():
    path = incident_output_path("cloudflare-verizon-2019", "104.16.0.0/12", single=True)
    assert path.name == "cloudflare_verizon_2019.json"


def test_incident_output_path_multi_prefix():
    path = incident_output_path("some-incident", "104.16.0.0/12", single=False)
    assert path.name == "some_incident_104.16.0.0_12.json"
