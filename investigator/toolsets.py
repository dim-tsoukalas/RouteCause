"""Toolset manifest loader (Phase 2 pluggable toolset abstraction).

Mirrors HolmesGPT's YAML-defined toolset model -- a config-driven list of
tools instead of hardcoded imports -- using stdlib `tomllib` rather than
YAML/PyYAML, so the core still has zero required dependencies.

Adding a new analyzer is a one-file-plus-one-manifest-entry operation: write
a module implementing the existing `Analyzer` protocol
(investigator/analyzers/base.py, unchanged) and add a `[[toolset]]` block to
toolsets.toml. Nothing here, in engine.py, or in cli.py needs to change.
"""
from __future__ import annotations

import importlib
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path

DEFAULT_TOOLSETS_PATH = Path(__file__).resolve().parent / "toolsets.toml"


@dataclass(frozen=True)
class ToolsetEntry:
    name: str
    kind: str            # "analyzer" (only kind so far; "retrieval" is a
                          # reserved future kind for non-analyzer tools)
    module: str
    enabled: bool
    description: str = ""


def load_toolsets(path: str | Path = DEFAULT_TOOLSETS_PATH) -> list[ToolsetEntry]:
    raw = tomllib.loads(Path(path).read_text())
    return [
        ToolsetEntry(
            name=t["name"],
            kind=t["kind"],
            module=t["module"],
            enabled=t.get("enabled", True),
            description=t.get("description", ""),
        )
        for t in raw.get("toolset", [])
    ]


def load_rfc_search_config(path: str | Path = DEFAULT_TOOLSETS_PATH) -> dict:
    """The `[rfc_search]` table -- non-analyzer toolset config consumed by
    `investigator.agent.AgentLoop` for its context-budget cap."""
    raw = tomllib.loads(Path(path).read_text())
    return raw.get("rfc_search", {})


def load_citation_eval_config(path: str | Path = DEFAULT_TOOLSETS_PATH) -> dict:
    """The `[citation_eval]` table -- consumed by
    `investigator.evaluation.entailment.default_checker()`."""
    raw = tomllib.loads(Path(path).read_text())
    return raw.get("citation_eval", {})


def register_enabled_analyzers(entries: list[ToolsetEntry]) -> None:
    """Dynamically imports each enabled analyzer-kind module, which triggers
    its `@register` decorator (investigator/analyzers/base.py) as a side
    effect -- this *is* the registration; there's nothing else to call.

    If a module was already imported earlier in this process (e.g. the
    default manifest's analyzers, registered when `investigator.analyzers`
    was first imported), a plain `import_module` is a no-op -- Python caches
    modules and won't re-run their top-level code, so `@register` wouldn't
    fire again. Reload it instead so a caller that `reset_registry()`-ed
    first (see InvestigationEngine, for a non-default `--toolsets` manifest)
    actually gets its analyzers back."""
    for entry in entries:
        if entry.kind != "analyzer" or not entry.enabled:
            continue
        if entry.module in sys.modules:
            importlib.reload(sys.modules[entry.module])
        else:
            importlib.import_module(entry.module)
