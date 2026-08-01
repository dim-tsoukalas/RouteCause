"""AS_PATH loop analyzer.

RFC 4271 §9.1.2 requires a BGP speaker to reject routes whose AS_PATH contains
its own AS number (loop detection). An AS appearing more than once in an
AS_PATH is therefore a concrete, checkable anomaly (a loop, or aggressive
prepending worth surfacing).

Grounding: RFC 4271 (BGP-4), AS_PATH attribute and loop detection.
"""
from __future__ import annotations

from collections import Counter

from investigator.analyzers.base import register
from investigator.types import Finding, Incident, Result


@register
class ASPathLoopAnalyzer:
    kind = "ASPathLoop"

    def analyze(self, incident: Incident) -> list[Result]:
        findings: list[Finding] = []
        evidence: list[str] = []

        for u in incident.updates:
            if u.kind != "announce" or not u.as_path:
                continue
            counts = Counter(u.as_path)
            repeated = {asn: c for asn, c in counts.items() if c > 1}
            if repeated:
                detail = ", ".join(f"AS{asn}×{c}" for asn, c in repeated.items())
                findings.append(
                    Finding(
                        text=(
                            f"AS_PATH {list(u.as_path)} for {u.prefix} repeats: {detail}. "
                            f"RFC 4271 §9.1.2 mandates loop detection on the local AS number."
                        ),
                        rfc_hint="RFC 4271 AS_PATH loop detection",
                    )
                )
                evidence.append(u.evidence_ref)

        if not findings:
            return []

        return [
            Result(
                kind=self.kind,
                name=incident.prefix,
                findings=findings,
                details=f"{len(findings)} announcement(s) with a repeated ASN in AS_PATH.",
                evidence=evidence,
                severity="warning",
            )
        ]
