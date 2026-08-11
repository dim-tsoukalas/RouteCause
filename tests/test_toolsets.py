from investigator.analyzers.base import all_analyzers, registered_kinds, reset_registry
from investigator.toolsets import (
    load_rfc_search_config,
    load_toolsets,
    register_enabled_analyzers,
)

FIXTURE_TOML = """
[[toolset]]
name = "moas"
kind = "analyzer"
module = "investigator.analyzers.moas"
enabled = true
description = "MOAS only, for this fixture"

[[toolset]]
name = "withdrawal_storm"
kind = "analyzer"
module = "investigator.analyzers.withdrawal_storm"
enabled = false
description = "disabled on purpose"

[rfc_search]
max_context_chars = 999
"""


def _write_fixture(tmp_path):
    path = tmp_path / "toolsets.toml"
    path.write_text(FIXTURE_TOML)
    return path


def test_load_toolsets_parses_entries(tmp_path):
    path = _write_fixture(tmp_path)
    entries = load_toolsets(path)
    assert [e.name for e in entries] == ["moas", "withdrawal_storm"]
    assert entries[0].enabled is True
    assert entries[1].enabled is False
    assert entries[0].module == "investigator.analyzers.moas"


def test_load_rfc_search_config(tmp_path):
    path = _write_fixture(tmp_path)
    assert load_rfc_search_config(path) == {"max_context_chars": 999}


def test_disabled_entries_are_not_registered(tmp_path):
    path = _write_fixture(tmp_path)
    reset_registry()
    try:
        register_enabled_analyzers(load_toolsets(path))
        assert "MOAS" in registered_kinds()
        assert "WithdrawalStorm" not in registered_kinds()
    finally:
        # restore the real default set so later tests in the same process
        # (e.g. tests/test_analyzers.py) aren't affected by this one.
        reset_registry()
        from investigator.toolsets import load_toolsets as _lt
        register_enabled_analyzers(_lt())


def test_subset_manifest_registers_only_that_subset(tmp_path):
    path = _write_fixture(tmp_path)
    reset_registry()
    try:
        register_enabled_analyzers(load_toolsets(path))
        assert len(all_analyzers()) == 1
        assert registered_kinds() == ["MOAS"]
    finally:
        reset_registry()
        from investigator.toolsets import load_toolsets as _lt
        register_enabled_analyzers(_lt())
