"""RPKI/ROA validation analyzer (docs/alignment-plan.md item 8).

Proves the toolset abstraction with a genuinely independent evidence axis
(RPKI, not more RFC prose) rather than just claiming it's possible: this is
a new module plus one `[[toolset]]` entry, zero changes to `engine.py`,
`cli.py`, or the registry machinery -- the diff itself is the evidence, per
this item's own done-criterion.

Reads `investigator/rpki.py`'s local cache (`data/rpki_cache.json`),
populated by a separate, explicit fetch step
(`python -m investigator.rpki catalog <name>`) -- the same "fetch once,
analyze offline" split `investigator/ingest.py` uses for raw MRT data, so
this stays a pure, offline, deterministic `Analyzer` like every other one
here: no network call happens during `analyze()`. An incident with no
cached data for its observed (prefix, origin) pairs produces no finding --
silently incomplete, not a crash or a fabricated result, same
abstain-rather-than-guess discipline as everything else in this project.

CAVEAT, carried into every finding's text, not just this docstring: RPKI
validation reflects *today's* registration, not necessarily the state at
the time of a historical incident -- see `investigator/rpki.py`'s module
docstring for why, including a directly-verified case where it matters.
"""
from __future__ import annotations

from investigator.analyzers.base import register
from investigator.rpki import CACHE_PATH, load_cache, observed_prefix_origin_pairs
from investigator.types import Finding, Incident, Result


@register
class RPKIAnalyzer:
    kind = "RPKIViolation"

    def analyze(self, incident: Incident) -> list[Result]:
        cache = load_cache(CACHE_PATH)

        violations: list[tuple[str, int, dict, list[str]]] = []
        for prefix, asn in sorted(observed_prefix_origin_pairs(incident)):
            entry = cache.get(f"{prefix}|{asn}")
            if entry is None or entry.get("status") != "invalid_asn":
                continue  # not fetched, or not a violation -- no claim made either way
            refs = [
                u.evidence_ref
                for u in incident.updates
                if u.kind == "announce" and u.prefix == prefix and u.origin_asn == asn
            ]
            violations.append((prefix, asn, entry, refs))

        if not violations:
            return []

        findings = [
            Finding(
                text=(
                    f"AS{asn} announced {prefix}, but current RPKI ROA data does not "
                    f"authorize that origin for this prefix (validity: {entry['status']}, "
                    f"{len(entry['validating_roas'])} covering ROA(s) found for a different "
                    f"origin). Reflects today's RPKI registration, not necessarily the state "
                    f"at the time of this incident."
                ),
                rfc_hint="RPKI Route Origin Validation (ROV) / ROA authorization",
            )
            for prefix, asn, entry, _ in violations
        ]
        evidence = [ref for _, _, _, refs in violations for ref in refs]

        return [
            Result(
                kind=self.kind,
                name=incident.prefix,
                findings=findings,
                details=(
                    f"{len(violations)} observed origin(s) not authorized by current "
                    f"RPKI ROA data."
                ),
                evidence=evidence,
                severity="critical",
            )
        ]
