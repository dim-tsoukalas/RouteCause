from pathlib import Path

import pytest

from investigator.cli import _resolve_incident_path


def test_resolves_direct_path_unchanged():
    path = Path("data/incidents/incident_moas_withdrawal.json")
    assert _resolve_incident_path(str(path)) == path


def test_resolves_bare_catalog_name_with_hyphens():
    resolved = _resolve_incident_path("pakistan-youtube-2008")
    assert resolved.name == "pakistan_youtube_2008.json"
    assert resolved.is_file()


def test_raises_helpful_error_for_unknown_name():
    with pytest.raises(SystemExit, match="no incident found for 'not-a-real-incident'"):
        _resolve_incident_path("not-a-real-incident")
