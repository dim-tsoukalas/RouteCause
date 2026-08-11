"""MOAS analyzer: Multiple-Origin-AS detection.

A prefix legitimately originated by exactly one AS that suddenly appears with
a *different* origin AS is the classic signature of a prefix hijack (or a
misconfiguration / intentional MOAS). This is a deterministic, well-defined
check — no LLM required.

Grounding: BGP-4 origin semantics (RFC 4271); hijack/MOAS background (RFC 7908
route leaks, and MOAS discussion in the routing-security literature).
"""
from __future__ import annotations

from collections import defaultdict

from investigator.analyzers.base import register
from investigator.types import Finding, Incident, Result


@register
class MOASAnalyzer:
    kind = "MOAS"

    def analyze(self, incident: Incident) -> list[Result]:
        # Map origin_asn -> the evidence lines that announced it.
        origins: dict[int, list[str]] = defaultdict(list)
        for u in incident.updates:
            if u.kind == "announce" and u.origin_asn is not None and u.prefix == incident.prefix:
                origins[u.origin_asn].append(u.evidence_ref)

        if len(origins) <= 1:
            return []  # single origin (or none) -> nothing to report

        # Heuristic: the origin with the earliest/most announcements is the
        # presumed legitimate one; the rest are anomalous.
        ranked = sorted(origins.items(), key=lambda kv: len(kv[1]), reverse=True)
        legit_asn, _ = ranked[0]
        anomalous = ranked[1:]

        findings = [
            Finding(
                text=(
                    f"Prefix {incident.prefix} was announced by "
                    f"{len(origins)} distinct origin ASNs "
                    f"({', '.join(f'AS{a}' for a in origins)}). Expected a single "
                    f"origin; presumed legitimate origin is AS{legit_asn}."
                ),
                rfc_hint="BGP origin AS semantics and prefix hijack (MOAS)",
            )
        ]
        evidence: list[str] = []
        for asn, refs in anomalous:
            evidence.extend(refs)
            findings.append(
                Finding(
                    text=f"Anomalous origin AS{asn} advertised {incident.prefix} "
                         f"({len(refs)} announcement(s)).",
                    rfc_hint="unauthorized origination / route hijack",
                )
            )

        return [
            Result(
                kind=self.kind,
                name=incident.prefix,
                findings=findings,
                details=f"{len(origins)} origin ASNs observed for a single prefix.",
                evidence=evidence,
                severity="critical",
            )
        ]
