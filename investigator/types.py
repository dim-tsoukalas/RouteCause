"""Core domain types.

The `Result` / `Finding` shapes deliberately mirror K8sGPT's
`common.Result` / `common.Failure` pattern: deterministic analyzers emit
structured findings with *no* LLM involvement, and an optional LLM
enrichment step consumes them later. Keeping detection LLM-free is what
keeps hallucination out of the detection path.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path


# --------------------------------------------------------------------------- #
# Incident evidence model (the structured input a real BGP feed would produce)
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class BGPUpdate:
    """A single BGP update line of evidence.

    `kind` is "announce" or "withdraw". For withdrawals, as_path/origin_asn
    are typically absent.
    """
    timestamp: datetime
    kind: str
    prefix: str
    peer_asn: int
    as_path: tuple[int, ...] = ()
    origin_asn: int | None = None
    collector: str = "unknown"

    @property
    def evidence_ref(self) -> str:
        """A stable, human-readable citation handle for this raw line."""
        ts = self.timestamp.strftime("%Y-%m-%dT%H:%M:%SZ")
        if self.kind == "withdraw":
            return f"{self.collector}@{ts} WITHDRAW {self.prefix} peer=AS{self.peer_asn}"
        path = " ".join(str(a) for a in self.as_path)
        return (
            f"{self.collector}@{ts} ANNOUNCE {self.prefix} "
            f"origin=AS{self.origin_asn} path=[{path}] peer=AS{self.peer_asn}"
        )


@dataclass
class Incident:
    """A curated incident: metadata plus the raw BGP evidence stream."""
    incident_id: str
    description: str
    prefix: str
    updates: list[BGPUpdate] = field(default_factory=list)
    source: str = "unknown"          # e.g. "RIPE RIS rrc00" or "synthetic"
    ground_truth: str | None = None  # label, if known — kept out of the analyzers

    @classmethod
    def from_json(cls, path: str | Path) -> "Incident":
        raw = json.loads(Path(path).read_text())
        updates = [
            BGPUpdate(
                timestamp=_parse_ts(u["timestamp"]),
                kind=u["kind"],
                prefix=u["prefix"],
                peer_asn=int(u["peer_asn"]),
                as_path=tuple(int(a) for a in u.get("as_path", [])),
                origin_asn=(int(u["origin_asn"]) if u.get("origin_asn") is not None else None),
                collector=u.get("collector", "unknown"),
            )
            for u in raw["updates"]
        ]
        return cls(
            incident_id=raw["incident_id"],
            description=raw.get("description", ""),
            prefix=raw["prefix"],
            updates=updates,
            source=raw.get("source", "unknown"),
            ground_truth=raw.get("ground_truth"),
        )


def _parse_ts(value: str) -> datetime:
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


# --------------------------------------------------------------------------- #
# Analyzer output model (mirrors K8sGPT Result / Failure)
# --------------------------------------------------------------------------- #
@dataclass
class Finding:
    """One observed problem. `rfc_hint` is the analog of K8sGPT's KubernetesDoc:
    a pointer to the concept the retrieval layer should ground this in."""
    text: str
    rfc_hint: str | None = None
    sensitive: bool = False


@dataclass
class Result:
    """Structured, deterministic output of a single analyzer run.

    Every Result is a *computed fact* about the evidence, each traceable back
    to specific raw update lines via `evidence`.
    """
    kind: str                       # analyzer kind, e.g. "MOAS"
    name: str                       # the object under analysis, e.g. the prefix
    findings: list[Finding] = field(default_factory=list)
    details: str = ""
    evidence: list[str] = field(default_factory=list)  # raw update evidence_refs
    severity: str = "info"          # info | warning | critical

    def is_empty(self) -> bool:
        return not self.findings
