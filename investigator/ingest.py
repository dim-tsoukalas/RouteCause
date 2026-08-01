"""Real-incident ingester.

Pulls raw MRT update streams for a prefix + time window directly from the
public RIPE RIS (data.ris.ripe.net) and RouteViews (archive.routeviews.org)
archives, filters to the target prefix, and normalizes the result into the
same Incident JSON shape `investigator.types.Incident.from_json` already
consumes - so every existing analyzer/CLI path works unmodified on real data.

Deliberately not PyBGPStream: that wraps a C library with no Windows wheels.
This uses only the standard library (urllib/gzip/bz2) plus the pure-Python
`mrtparse` package (a single dependency, no native/C toolchain required), so
it installs the same way on any platform.

Both archives are organized as one file per collector dump interval; this
module lists each month's directory rather than assuming a fixed interval,
since RIS uses ~5 minutes and RouteViews' cadence (and even its alignment to
the clock) has varied over the archive's history.

    PYTHONPATH=. python -m investigator.ingest fetch \\
        --prefix 104.16.0.0/12 --start 2019-06-24T10:00:00Z --end 2019-06-24T13:00:00Z \\
        --name cloudflare_verizon_2019 --collectors rrc00,route-views2 \\
        --ground-truth "route leak"

    PYTHONPATH=. python -m investigator.ingest catalog cloudflare-verizon-2019
"""
from __future__ import annotations

import argparse
import bz2
import gzip
import io
import json
import re
import sys
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

from mrtparse import Reader

from investigator.types import BGPUpdate, Incident

DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "incidents"
DEFAULT_CATALOG = DATA_DIR / "catalog.json"
DEFAULT_COLLECTORS = ["rrc00", "route-views2"]

_FILENAME_RE = re.compile(r"updates\.(\d{8})\.(\d{4})\.(gz|bz2)")
_LOOKBACK = timedelta(minutes=20)  # include the file whose interval may straddle `start`
_MSG_TYPE_UPDATE = 2
_AFI_IPV4 = 1
_ATTR_AS_PATH = 2


# --------------------------------------------------------------------------- #
# Archive addressing (list-then-filter, robust to varying dump cadences)
# --------------------------------------------------------------------------- #
def _is_routeviews(collector: str) -> bool:
    return collector.startswith("route-views")


def _month_dir_url(collector: str, month_start: datetime) -> str:
    if _is_routeviews(collector):
        return f"http://archive.routeviews.org/{collector}/bgpdata/{month_start:%Y.%m}/UPDATES/"
    return f"https://data.ris.ripe.net/{collector}/{month_start:%Y.%m}/"


def _iter_months(start: datetime, end: datetime):
    y, m = start.year, start.month
    while (y, m) <= (end.year, end.month):
        yield datetime(y, m, 1, tzinfo=timezone.utc)
        m += 1
        if m > 12:
            m, y = 1, y + 1


def _collector_file_urls(collector: str, start: datetime, end: datetime) -> list[str]:
    urls: list[str] = []
    for month_start in _iter_months(start, end):
        dir_url = _month_dir_url(collector, month_start)
        try:
            listing = _download(dir_url).decode("utf-8", errors="ignore")
        except urllib.error.URLError as exc:
            print(f"warning: could not list {dir_url}: {exc}", file=sys.stderr)
            continue
        for match in _FILENAME_RE.finditer(listing):
            fname, date_part, time_part = match.group(0), match.group(1), match.group(2)
            ts = datetime.strptime(date_part + time_part, "%Y%m%d%H%M").replace(tzinfo=timezone.utc)
            if start - _LOOKBACK <= ts <= end:
                urls.append(dir_url + fname)
    return sorted(set(urls))


def _download(url: str, timeout: int = 60) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "network-investigator-ingest/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def _open_mrt(raw: bytes, url: str):
    buf = io.BytesIO(raw)
    return bz2.BZ2File(buf) if url.endswith(".bz2") else gzip.GzipFile(fileobj=buf)


# --------------------------------------------------------------------------- #
# MRT record -> BGPUpdate
# --------------------------------------------------------------------------- #
def _flatten_as_path(path_attributes: list[dict]) -> list[int]:
    for attr in path_attributes:
        if _ATTR_AS_PATH in attr.get("type", {}):
            asns: list[int] = []
            for segment in attr.get("value", []):
                asns.extend(int(a) for a in segment.get("value", []))
            return asns
    return []


def extract_updates(entry_data: dict, target_prefixes: set[str], collector: str) -> list[BGPUpdate]:
    """Pure transform: one parsed MRT record -> zero or more BGPUpdate for any
    prefix in `target_prefixes`. No I/O, so it's directly unit-testable against
    a fixture. Accepting a set (not just one prefix) lets a single archive-file
    pass serve every prefix in a multi-prefix incident, instead of re-fetching
    the same files once per prefix."""
    bgp_msg = entry_data.get("bgp_message")
    if not bgp_msg or _MSG_TYPE_UPDATE not in bgp_msg.get("type", {}):
        return []
    if _AFI_IPV4 not in entry_data.get("afi", {}):
        return []

    ts_key = next(iter(entry_data["timestamp"]))
    ts = datetime.fromtimestamp(int(ts_key), tz=timezone.utc)
    peer_asn = int(entry_data["peer_as"])

    updates: list[BGPUpdate] = []

    for w in bgp_msg.get("withdrawn_routes", []):
        prefix = f"{w['prefix']}/{w['length']}"
        if prefix in target_prefixes:
            updates.append(BGPUpdate(ts, "withdraw", prefix, peer_asn, (), None, collector))

    nlri = bgp_msg.get("nlri", [])
    if nlri:
        as_path = _flatten_as_path(bgp_msg.get("path_attributes", []))
        origin = as_path[-1] if as_path else None
        for n in nlri:
            prefix = f"{n['prefix']}/{n['length']}"
            if prefix in target_prefixes:
                updates.append(
                    BGPUpdate(ts, "announce", prefix, peer_asn, tuple(as_path), origin, collector)
                )

    return updates


def fetch_updates_for_prefixes(
    prefixes: list[str], start: datetime, end: datetime, collectors: list[str]
) -> dict[str, list[BGPUpdate]]:
    """Download + parse every archive file overlapping [start, end] for each
    collector *once*, filtered down to every prefix in `prefixes` in the same
    pass, then grouped back out per prefix. Network + parsing; not unit-tested
    directly (see `extract_updates` for the tested pure transform)."""
    target = set(prefixes)
    by_prefix: dict[str, list[BGPUpdate]] = {p: [] for p in prefixes}
    for collector in collectors:
        for url in _collector_file_urls(collector, start, end):
            try:
                raw = _download(url)
            except urllib.error.URLError as exc:
                print(f"warning: failed to fetch {url}: {exc}", file=sys.stderr)
                continue
            mrt = _open_mrt(raw, url)
            for entry in Reader(mrt):
                for u in extract_updates(entry.data, target, collector):
                    by_prefix[u.prefix].append(u)
    for prefix, updates in by_prefix.items():
        updates[:] = sorted((u for u in updates if start <= u.timestamp <= end), key=lambda u: u.timestamp)
    return by_prefix


def fetch_updates(
    prefix: str, start: datetime, end: datetime, collectors: list[str]
) -> list[BGPUpdate]:
    """Single-prefix convenience wrapper around `fetch_updates_for_prefixes`."""
    return fetch_updates_for_prefixes([prefix], start, end, collectors)[prefix]


# --------------------------------------------------------------------------- #
# Incident assembly + persistence
# --------------------------------------------------------------------------- #
def _source_note(collectors: list[str], start: datetime, end: datetime) -> str:
    return (
        f"RIPE RIS / RouteViews raw MRT archives ({', '.join(collectors)}), "
        f"{start:%Y-%m-%d %H:%M}-{end:%H:%M} UTC"
    )


def build_incident(
    incident_id: str,
    description: str,
    prefix: str,
    start: datetime,
    end: datetime,
    collectors: list[str],
    ground_truth: str | None,
) -> Incident:
    updates = fetch_updates(prefix, start, end, collectors)
    return Incident(
        incident_id=incident_id,
        description=description,
        prefix=prefix,
        updates=updates,
        source=_source_note(collectors, start, end),
        ground_truth=ground_truth,
    )


def build_incidents_for_prefixes(
    catalog_name: str,
    description: str,
    prefixes: list[str],
    start: datetime,
    end: datetime,
    collectors: list[str],
    ground_truth: str | None,
) -> dict[str, Incident]:
    """One archive-download pass, one Incident per prefix -- the multi-prefix
    counterpart of `build_incident`, used by the `catalog` CLI command so a
    5-prefix incident doesn't re-fetch the same files 5 times."""
    single = len(prefixes) == 1
    by_prefix = fetch_updates_for_prefixes(prefixes, start, end, collectors)
    source = _source_note(collectors, start, end)
    incidents: dict[str, Incident] = {}
    for prefix in prefixes:
        incident_id = catalog_name if single else f"{catalog_name}-{prefix}"
        incidents[prefix] = Incident(
            incident_id=incident_id,
            description=description,
            prefix=prefix,
            updates=by_prefix[prefix],
            source=source,
            ground_truth=ground_truth,
        )
    return incidents


def save_incident(incident: Incident, path: Path) -> None:
    payload = {
        "incident_id": incident.incident_id,
        "description": incident.description,
        "prefix": incident.prefix,
        "source": incident.source,
        "ground_truth": incident.ground_truth,
        "updates": [
            {
                "timestamp": u.timestamp.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "kind": u.kind,
                "prefix": u.prefix,
                "peer_asn": u.peer_asn,
                "as_path": list(u.as_path),
                "origin_asn": u.origin_asn,
                "collector": u.collector,
            }
            for u in incident.updates
        ],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2))


def incident_output_path(catalog_name: str, prefix: str, *, single: bool) -> Path:
    """The path a catalog entry's incident JSON is written to / read from.
    Shared with `investigator.evaluate` so both sides agree on the filename."""
    stem = catalog_name.replace("-", "_")
    if not single:
        stem = f"{stem}_{prefix.replace('/', '_')}"
    return DATA_DIR / f"{stem}.json"


# --------------------------------------------------------------------------- #
# Catalog
# --------------------------------------------------------------------------- #
def load_catalog(path: Path = DEFAULT_CATALOG) -> list[dict]:
    return json.loads(Path(path).read_text())


def find_catalog_entry(name: str, catalog: list[dict]) -> dict:
    for entry in catalog:
        if entry["name"] == name:
            return entry
    raise KeyError(f"no catalog entry named {name!r}")


def _parse_ts(value: str) -> datetime:
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="investigator.ingest", description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)

    fetch = sub.add_parser("fetch", help="fetch a prefix/time-window directly")
    fetch.add_argument("--prefix", required=True)
    fetch.add_argument("--start", required=True, help="ISO-8601, e.g. 2019-06-24T10:00:00Z")
    fetch.add_argument("--end", required=True)
    fetch.add_argument("--name", required=True, help="incident_id / output file stem")
    fetch.add_argument("--description", default="")
    fetch.add_argument("--ground-truth", default=None)
    fetch.add_argument(
        "--collectors",
        default=",".join(DEFAULT_COLLECTORS),
        help="comma-separated RIS rrcNN and/or RouteViews route-viewsX collectors",
    )
    fetch.add_argument("--output", default=None)

    cat = sub.add_parser("catalog", help="fetch a named incident from the catalog")
    cat.add_argument("name")
    cat.add_argument("--catalog-file", default=str(DEFAULT_CATALOG))
    cat.add_argument("--collectors", default=None, help="override the catalog entry's collectors")

    return p


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)

    if args.cmd == "fetch":
        start, end = _parse_ts(args.start), _parse_ts(args.end)
        collectors = [c.strip() for c in args.collectors.split(",") if c.strip()]
        incident = build_incident(
            args.name, args.description, args.prefix, start, end, collectors, args.ground_truth
        )
        out = Path(args.output) if args.output else DATA_DIR / f"{args.name}.json"
        save_incident(incident, out)
        print(f"wrote {out} ({len(incident.updates)} updates)")
        return 0

    if args.cmd == "catalog":
        catalog = load_catalog(Path(args.catalog_file))
        entry = find_catalog_entry(args.name, catalog)
        start, end = _parse_ts(entry["start"]), _parse_ts(entry["end"])
        collectors = (
            [c.strip() for c in args.collectors.split(",")]
            if args.collectors
            else entry.get("collectors", DEFAULT_COLLECTORS)
        )
        ground_truth = ", ".join(entry.get("expected", [])) or None
        prefixes = entry["prefixes"]
        single = len(prefixes) == 1
        incidents = build_incidents_for_prefixes(
            entry["name"], entry.get("description", ""), prefixes, start, end, collectors, ground_truth
        )
        for prefix, incident in incidents.items():
            out = incident_output_path(entry["name"], prefix, single=single)
            save_incident(incident, out)
            print(f"wrote {out} ({len(incident.updates)} updates)")
        return 0

    return 1


if __name__ == "__main__":
    sys.exit(main())
