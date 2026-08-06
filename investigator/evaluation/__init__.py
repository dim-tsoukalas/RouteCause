"""Citation-correctness evaluation harness (Phase 3).

Distinct from `investigator.evaluate` (Phase 1.5), which measures whether
the *deterministic analyzers* detect the right incident type. This measures
whether the *LLM's cited explanation* actually says something its cited
source supports -- citation presence is not citation correctness.
"""
