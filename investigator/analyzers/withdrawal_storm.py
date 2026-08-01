"""Withdrawal-storm analyzer.

Detects a burst of withdrawals for the prefix within a short window — the
observable signature of a session flap, an upstream outage, or de-aggregation
churn. Deterministic: it counts and rate-checks, it does not guess the cause
(the LLM enrichment / hypothesis phases do that, grounded in these facts).
"""
from __future__ import annotations

from datetime import timedelta

from investigator.analyzers.base import register
from investigator.types import Finding, Incident, Result

WINDOW = timedelta(minutes=5)
STORM_THRESHOLD = 5  # withdrawals within WINDOW to qualify as a "storm"


@register
class WithdrawalStormAnalyzer:
    kind = "WithdrawalStorm"

    def analyze(self, incident: Incident) -> list[Result]:
        withdrawals = sorted(
            (u for u in incident.updates
             if u.kind == "withdraw" and u.prefix == incident.prefix),
            key=lambda u: u.timestamp,
        )
        if len(withdrawals) < STORM_THRESHOLD:
            return []

        # Sliding window: find the densest burst.
        best_count = 0
        best_span = (withdrawals[0], withdrawals[0])
        start = 0
        for end in range(len(withdrawals)):
            while withdrawals[end].timestamp - withdrawals[start].timestamp > WINDOW:
                start += 1
            count = end - start + 1
            if count > best_count:
                best_count = count
                best_span = (withdrawals[start], withdrawals[end])

        if best_count < STORM_THRESHOLD:
            return []

        peers = sorted({u.peer_asn for u in withdrawals})
        evidence = [u.evidence_ref for u in withdrawals]
        return [
            Result(
                kind=self.kind,
                name=incident.prefix,
                findings=[
                    Finding(
                        text=(
                            f"{best_count} withdrawals of {incident.prefix} within "
                            f"{int(WINDOW.total_seconds() // 60)} minutes "
                            f"({best_span[0].timestamp:%H:%M:%S}–{best_span[1].timestamp:%H:%M:%S}), "
                            f"across {len(peers)} peer(s): "
                            f"{', '.join('AS%d' % p for p in peers)}."
                        ),
                        rfc_hint="BGP UPDATE withdrawal / route unreachability",
                    )
                ],
                details=f"Total {len(withdrawals)} withdrawals; peak burst {best_count} in window.",
                evidence=evidence,
                severity="warning",
            )
        ]
