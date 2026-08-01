"""network-investigator — a citation-grounded network incident investigator.

Phase 1 (baseline parity): deterministic analyzers + cited RFC retrieval +
pluggable LLM backend, exposed via a CLI. Later phases add competing
hypotheses, adversarial retrieval, abstention, and a citation-correctness eval.
"""
from investigator.engine import InvestigationEngine  # noqa: F401
from investigator.types import BGPUpdate, Finding, Incident, Result  # noqa: F401

__version__ = "0.1.0"
