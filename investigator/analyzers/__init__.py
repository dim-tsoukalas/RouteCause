"""Importing this package registers every *enabled* analyzer from the
toolset manifest (investigator/toolsets.toml).

New analyzers (Phase 2+) don't get imported here anymore -- add a module
implementing the `Analyzer` protocol plus one `[[toolset]]` entry in
toolsets.toml, and it self-registers on import. Zero changes to this file,
engine.py, or cli.py.
"""
from investigator.analyzers.base import (  # noqa: F401
    Analyzer,
    all_analyzers,
    get_analyzer,
    register,
    registered_kinds,
)
from investigator.toolsets import load_toolsets, register_enabled_analyzers

register_enabled_analyzers(load_toolsets())
