"""Investigation report model + renderer.

The report mirrors the structure the full vision calls for: grounded
observations (from deterministic analyzers, each tied to raw evidence), a
cited explanation (from RFC retrieval), and next-step checks. Competing-
hypothesis / contradicting-evidence / citation-correctness scoring
(investigator/ach.py, investigator/retrieval/contradiction.py,
investigator/evaluation/) hang off this report via CLI flags rather than
living in the report body itself, so the core shape here stays stable.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from investigator.retrieval.citations import CitedAnswer
from investigator.types import Result


@dataclass
class Report:
    incident_id: str
    question: str
    results: list[Result] = field(default_factory=list)
    explanation: CitedAnswer | None = None
    next_steps: list[str] = field(default_factory=list)

    @property
    def has_findings(self) -> bool:
        return any(not r.is_empty() for r in self.results)

    def render(self) -> str:
        out: list[str] = []
        out.append(f"# Investigation: {self.incident_id}")
        out.append(f"_Question: {self.question}_\n")

        # --- Observations (deterministic, grounded in raw evidence) ---------
        out.append("## Observations (computed from evidence)")
        if not self.has_findings:
            out.append("No anomalies detected by the deterministic analyzers.\n")
        for r in self.results:
            if r.is_empty():
                continue
            out.append(f"### [{r.severity.upper()}] {r.kind} — {r.name}")
            for f in r.findings:
                hint = f" _(ground in: {f.rfc_hint})_" if f.rfc_hint else ""
                out.append(f"- {f.text}{hint}")
            if r.evidence:
                out.append("  - Evidence:")
                for e in r.evidence[:8]:
                    out.append(f"    - `{e}`")
                if len(r.evidence) > 8:
                    out.append(f"    - …and {len(r.evidence) - 8} more")
            out.append("")

        # --- Explanation (cited RFC grounding) ------------------------------
        out.append("## Explanation (grounded in reference docs)")
        if self.explanation is None:
            out.append("_No explanation generated._\n")
        elif self.explanation.abstained:
            out.append("**Abstained:** insufficient grounded evidence to explain "
                       "this from the reference corpus.\n")
        else:
            out.append(self.explanation.render() + "\n")

        # --- Next steps -----------------------------------------------------
        out.append("## Suggested next checks")
        if self.next_steps:
            for step in self.next_steps:
                out.append(f"- {step}")
        else:
            out.append("- (none)")

        # --- Footer ----------------------------------------------------------
        out.append("\n---")
        out.append("_Citation-correctness scoring (`--score-citations`), adversarial "
                   "counter-evidence retrieval, and competing-hypothesis (ACH) ranking "
                   "are all available now via `--seek-contradictions` -- see "
                   "investigator/evaluation/, investigator/retrieval/contradiction.py, "
                   "and investigator/ach.py._")
        return "\n".join(out)
