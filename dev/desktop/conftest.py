from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'src'), str(ROOT / 'src/looks'), str(ROOT / 'src/looks/tests')]


import pytest


@pytest.fixture(autouse=True)
def legacy_chinese_interface(monkeypatch):
    """Existing UI assertions exercise a user retaining the original language."""
    from desktopapp import i18n, window
    monkeypatch.setattr(i18n, '_language', 'zh_CN')
    original = window.load_settings
    monkeypatch.setattr(window, 'load_settings', lambda: {'language': 'zh_CN', **original()})
