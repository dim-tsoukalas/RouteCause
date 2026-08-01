"""Analyzer interface + registry.

Mirrors K8sGPT's `IAnalyzer` (`Analyze(...) -> []Result`) and its
`coreAnalyzerMap`. Analyzers register themselves via `@register`, and the
engine iterates the registry. Adding a new detector (Phase 2) is a one-file,
zero-core-change operation.
"""
from __future__ import annotations

from typing import Protocol, runtime_checkable

from investigator.types import Incident, Result


@runtime_checkable
class Analyzer(Protocol):
    kind: str

    def analyze(self, incident: Incident) -> list[Result]:
        ...


# Registry: name -> analyzer instance (the coreAnalyzerMap equivalent).
_REGISTRY: dict[str, Analyzer] = {}


def register(cls):
    """Class decorator that instantiates and registers an analyzer."""
    instance = cls()
    if not getattr(instance, "kind", None):
        raise ValueError(f"{cls.__name__} must define a non-empty `kind`")
    if instance.kind in _REGISTRY:
        raise ValueError(f"duplicate analyzer kind: {instance.kind}")
    _REGISTRY[instance.kind] = instance
    return cls


def all_analyzers() -> list[Analyzer]:
    return list(_REGISTRY.values())


def get_analyzer(kind: str) -> Analyzer | None:
    return _REGISTRY.get(kind)


def registered_kinds() -> list[str]:
    return sorted(_REGISTRY)
