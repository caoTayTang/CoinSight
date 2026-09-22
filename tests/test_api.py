from pathlib import Path

from app.api import dashboard, health


def test_health():
    assert health() == {"status": "ok"}


def test_dashboard_file_exists():
    response = dashboard()
    assert Path(response.path).is_file()
