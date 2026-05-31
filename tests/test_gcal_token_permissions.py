from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_auth_gcal_sets_private_permissions_when_writing_token():
    source = (ROOT / "scripts" / "auth_gcal.py").read_text(encoding="utf-8")
    assert "os.open" in source
    assert "os.fchmod" in source
    assert "0o600" in source


def test_google_calendar_manager_sets_private_permissions_when_saving_token():
    source = (ROOT / "cal_system" / "google_calendar_manager.py").read_text(encoding="utf-8")
    assert "os.open" in source
    assert "os.fchmod" in source
    assert "0o600" in source
