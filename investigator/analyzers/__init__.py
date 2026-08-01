"""Importing this package registers all built-in analyzers.

New analyzers (Phase 2+) only need to be imported here to join the registry.
"""
from investigator.analyzers.base import (  # noqa: F401
    Analyzer,
    all_analyzers,
    get_analyzer,
    register,
    registered_kinds,
)

# Side-effect imports: each module self-registers via @register.
from investigator.analyzers import moas            # noqa: F401,E402
from investigator.analyzers import withdrawal_storm  # noqa: F401,E402
from investigator.analyzers import as_path_loop     # noqa: F401,E402
