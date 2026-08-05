"""Investigation engine.

Ties the two layers together, in the K8sGPT spirit:
  1. Run every deterministic analyzer over the incident (no LLM). -> Results
  2. For each finding, retrieve cited RFC grounding via an agentic loop
     (AgentLoop) that may search the RFC corpus more than once.
  3. Optionally narrate with an LLM backend (enrichment only).
The engine never invents facts; observations are computed and the explanation
is constrained to cite retrieved sources or abstain. Layer 1 is unconditional
and LLM-free; only Layer 2 is agentic — see investigator/agent.py for why
that split is deliberate.
"""
from __future__ import annotations

from investigator.agent import AgentLoop
from investigator.analyzers import all_analyzers
from investigator.llm import LLMBackend, default_backend
from investigator.report import Report
from investigator.retrieval.citations import CitationEngine
from investigator.retrieval.corpus import load_corpus
from investigator.types import Incident


class InvestigationEngine:
    def __init__(
        self,
        rfc_dir: str,
        backend: LLMBackend | None = None,
        max_search_rounds: int = 3,
    ):
        self.backend = backend or default_backend()
        self.citations = CitationEngine(load_corpus(rfc_dir), backend=self.backend)
        self.agent = AgentLoop(self.citations, self.backend, max_iterations=max_search_rounds)

    def investigate(self, incident: Incident, question: str) -> Report:
        # Layer 1: deterministic detection.
        results = []
        for analyzer in all_analyzers():
            results.extend(analyzer.analyze(incident))

        report = Report(incident_id=incident.incident_id, question=question, results=results)

        # Layer 2: cited grounding via the agentic search loop. Seed it with a
        # query built from the question plus the finding hints, so the first
        # search is anchored to what was actually observed; the loop may then
        # search further before answering.
        hints = [
            f.rfc_hint
            for r in results
            for f in r.findings
            if f.rfc_hint
        ]
        seed_query = question
        if hints:
            seed_query = f"{question} ({'; '.join(dict.fromkeys(hints))})"
        report.explanation = self.agent.run(question, seed_query=seed_query)

        report.next_steps = self._next_steps(results)
        return report

    def ask(self, question: str):
        """Doc-only Q&A path (the `ask` verb) — agentic retrieval + citation, no analyzers."""
        return self.agent.run(question, seed_query=question)

    @staticmethod
    def _next_steps(results) -> list[str]:
        steps: list[str] = []
        kinds = {r.kind for r in results if not r.is_empty()}
        if "MOAS" in kinds:
            steps.append("Confirm the legitimate origin AS against RPKI ROAs / IRR objects.")
            steps.append("Check whether the anomalous origin is an upstream leak or a hijack.")
        if "WithdrawalStorm" in kinds:
            steps.append("Correlate withdrawal timestamps with upstream session state / flap logs.")
        if "ASPathLoop" in kinds:
            steps.append("Inspect route-maps/prepending config on the ASes repeated in AS_PATH.")
        if not steps:
            steps.append("No anomalies detected; verify the evidence window covers the incident.")
        return steps
