"""RPKI/ROA validation fetcher + local cache (docs/alignment-plan.md item 8).

For every distinct (prefix, origin_asn) pair actually observed in an
incident's raw announce updates, queries RIPE NCC's public RIPEstat
`rpki-validation` data API (no auth, no key: `stat.ripe.net/data/rpki-
validation`) and caches the result locally -- the same "fetch once, analyze
offline" split `investigator/ingest.py` already uses for raw MRT data, so
`investigator/analyzers/rpki.py`'s `RPKIAnalyzer` stays a pure, offline,
deterministic `Analyzer`: no network call happens during `analyze()`, same
as every other analyzer in this project.

CAVEAT, stated plainly here and carried into every finding's text, not
glossed over: this is *today's* RPKI state, not necessarily the state at
the time of a historical incident. RPKI itself didn't exist before ~2011,
so for incidents older than that (e.g. `pakistan-youtube-2008`), "no ROA"
is expected and uninformative -- not evidence of anything. Even for
post-2011 incidents, address-block ownership and RPKI registration can
change over a decade; verified directly, not assumed, that this matters:
neither of `pakistan-youtube-2008`'s two contenders (AS17557, AS36561) is
today's valid origin for 208.65.153.0/24 (that's AS36040 now) -- current
ROA state doesn't cleanly settle who was right in 2008. This toolset's
strongest, least-caveated signal is on *recent* incidents, where current
ROA state is far more likely to still reflect incident-time reality.

    PYTHONPATH=. python -m investigator.rpki catalog pakistan-youtube-2008
    PYTHONPATH=. python -m investigator.rpki fetch-all
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

from investigator.ingest import DATA_DIR as INCIDENTS_DIR
from investigator.ingest import (
    DEFAULT_CATALOG,
    find_catalog_entry,
    incident_output_path,
    load_catalog,
)
from investigator.types import Incident

CACHE_PATH = Path(__file__).resolve().parent.parent / "data" / "rpki_cache.json"
_API_URL = "https://stat.ripe.net/data/rpki-validation/data.json"
_TIMEOUT_SECONDS = 15


def observed_prefix_origin_pairs(incident: Incident) -> set[tuple[str, int]]:
    """Every (prefix, origin_asn) actually announced in the raw evidence --
    not just `incident.prefix` alone, since a MOAS incident's whole point is
    more than one origin claiming the same prefix."""
    return {
        (u.prefix, u.origin_asn)
        for u in incident.updates
        if u.kind == "announce" and u.origin_asn is not None
    }


def _cache_key(prefix: str, asn: int) -> str:
    return f"{prefix}|{asn}"


def load_cache(path: Path = CACHE_PATH) -> dict:
    if not path.exists():
        return {}
    return json.loads(path.read_text())


def save_cache(cache: dict, path: Path = CACHE_PATH) -> None:
    path.write_text(json.dumps(cache, indent=2, sort_keys=True) + "\n")


def fetch_validation(prefix: str, origin_asn: int) -> dict:
    """One RIPEstat rpki-validation lookup. Real network call -- guarded by
    the caller (`fetch_for_incident`) so a transient failure caches an
    honest "unknown" instead of crashing an otherwise-offline analysis
    pipeline or silently pretending nothing was checked."""
    url = f"{_API_URL}?resource={origin_asn}&prefix={prefix}"
    with urllib.request.urlopen(url, timeout=_TIMEOUT_SECONDS) as resp:
        payload = json.loads(resp.read())
    data = payload["data"]
    return {
        "status": data["status"],  # "valid" | "invalid_asn" | "invalid_length" | "unknown"
        "validating_roas": data["validating_roas"],
    }


def fetch_for_incident(incident: Incident, cache: dict) -> int:
    """Fetches + caches ROA validation for every (prefix, origin) pair in
    `incident` not already cached. Returns the number of new lookups made
    (cached hits don't re-fetch, same spirit as ingest.py not re-downloading
    an MRT file it already has)."""
    fetched = 0
    for prefix, asn in sorted(observed_prefix_origin_pairs(incident)):
        key = _cache_key(prefix, asn)
        if key in cache:
            continue
        try:
            cache[key] = fetch_validation(prefix, asn)
        except (urllib.error.URLError, TimeoutError, KeyError, json.JSONDecodeError) as exc:
            cache[key] = {"status": "unknown", "validating_roas": [], "error": str(exc)}
        fetched += 1
    return fetched


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="investigator.rpki", description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)

    single = sub.add_parser("fetch", help="fetch ROA validation for one already-ingested incident file")
    single.add_argument("incident_path")

    cat = sub.add_parser("catalog", help="fetch ROA validation for a named catalog incident")
    cat.add_argument("name")
    cat.add_argument("--catalog-file", default=str(DEFAULT_CATALOG))

    sub.add_parser("fetch-all", help="fetch ROA validation for every already-ingested incident file")

    return p


def _fetch_and_report(incident: Incident, cache: dict) -> None:
    fetched = fetch_for_incident(incident, cache)
    pairs = observed_prefix_origin_pairs(incident)
    print(f"{incident.incident_id}: {len(pairs)} (prefix, origin) pair(s), {fetched} new lookup(s)")


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    cache = load_cache()

    if args.cmd == "fetch":
        incident = Incident.from_json(Path(args.incident_path))
        _fetch_and_report(incident, cache)
        save_cache(cache)
        return 0

    if args.cmd == "catalog":
        catalog = load_catalog(Path(args.catalog_file))
        entry = find_catalog_entry(args.name, catalog)
        prefixes = entry["prefixes"]
        single = len(prefixes) == 1
        for prefix in prefixes:
            path = incident_output_path(entry["name"], prefix, single=single)
            if not path.exists():
                print(f"skip {path} (not ingested -- run investigator.ingest first)")
                continue
            incident = Incident.from_json(path)
            _fetch_and_report(incident, cache)
        save_cache(cache)
        return 0

    if args.cmd == "fetch-all":
        for path in sorted(INCIDENTS_DIR.glob("*.json")):
            if path.name == "catalog.json":
                continue
            incident = Incident.from_json(path)
            _fetch_and_report(incident, cache)
        save_cache(cache)
        return 0

    return 1


if __name__ == "__main__":
    sys.exit(main())
