"""Route-leak analyzer: newly-appearing shared transit AS detection.

A route leak (RFC 7908 §2) propagates an announcement beyond its intended
scope, usually by an AS becoming an unintended transit point for routes it
has no business carrying. Unlike a hijack (MOAS), the *origin* AS is
unchanged -- what changes is who ends up in the middle of the AS_PATH.

This is a heuristic, not proof of a policy violation: genuine leak detection
needs AS-relationship data (customer/provider/peer) this project doesn't
have. What's observable from the update stream alone: does a previously
uninvolved AS suddenly show up as an interior hop in multiple different
peers' paths to the same, unchanged origin? That's the closest thing to a
leak's public footprint that a bare BGPUpdate stream can support.

Deliberately distinct from MOAS: if the origin AS itself changes, that's
MOAS's territory, not this analyzer's -- a leak, by definition, does not
change who the route claims to originate from.
"""
from __future__ import annotations

from collections import defaultdict

from investigator.analyzers.base import register
from investigator.types import Finding, Incident, Result

MIN_DISTINCT_PEERS = 2  # a new interior AS must appear via >=N peers to count
MIN_ANNOUNCES = 4       # too little evidence below this to split before/after


def _interior_asns(as_path: tuple[int, ...]) -> tuple[int, ...]:
    """AS_PATH hops excluding the announcing peer's own leading hop and the
    origin (last hop) -- the "transit" portion of the path."""
    return as_path[1:-1] if len(as_path) > 2 else ()


@register
class RouteLeakAnalyzer:
    kind = "RouteLeak"

    def analyze(self, incident: Incident) -> list[Result]:
        announces = sorted(
            (u for u in incident.updates
             if u.kind == "announce" and u.prefix == incident.prefix and u.as_path),
            key=lambda u: u.timestamp,
        )
        if len(announces) < MIN_ANNOUNCES:
            return []  # too little evidence to establish a "before" baseline

        t_min, t_max = announces[0].timestamp, announces[-1].timestamp
        if t_min == t_max:
            return []  # no time spread to split into before/after
        t_mid = t_min + (t_max - t_min) / 2

        baseline = [u for u in announces if u.timestamp <= t_mid]
        later = [u for u in announces if u.timestamp > t_mid]

        baseline_interior: set[int] = set()
        baseline_origins: set[int] = set()
        for u in baseline:
            baseline_interior.update(_interior_asns(u.as_path))
            if u.origin_asn is not None:
                baseline_origins.add(u.origin_asn)

        # new interior ASN -> {peer_asn -> one evidence_ref}
        sightings: dict[int, dict[int, str]] = defaultdict(dict)
        for u in later:
            if u.origin_asn not in baseline_origins:
                continue  # a changed origin is MOAS's signature, not this one's
            for asn in _interior_asns(u.as_path):
                if asn not in baseline_interior:
                    sightings[asn].setdefault(u.peer_asn, u.evidence_ref)

        qualifying = {
            asn: peers for asn, peers in sightings.items()
            if len(peers) >= MIN_DISTINCT_PEERS
        }
        if not qualifying:
            return []

        findings = [
            Finding(
                text=(
                    f"AS{asn} newly appears as a transit hop for {incident.prefix} "
                    f"across {len(peers)} distinct peer(s) partway through the "
                    f"observed window, with the origin AS unchanged -- consistent "
                    f"with a route leak (RFC 7908) rather than a hijack."
                ),
                rfc_hint="RFC 7908 route leak definition (scope violation, not origin change)",
            )
            for asn, peers in qualifying.items()
        ]
        evidence = [ref for peers in qualifying.values() for ref in peers.values()]

        return [
            Result(
                kind=self.kind,
                name=incident.prefix,
                findings=findings,
                details=(
                    f"{len(qualifying)} new transit AS(es) appeared mid-window across "
                    f">= {MIN_DISTINCT_PEERS} peers each, origin unchanged."
                ),
                evidence=evidence,
                severity="warning",
            )
        ]
