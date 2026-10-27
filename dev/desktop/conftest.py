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


DANGEROUS_PROGRAMS = ('sudo', 'pkill', 'kill', 'killall', 'pgrep', 'osascript')


def dangerous(argv):
    """The name of a command that would reach the administrator prompt or camera services, or None."""
    words = argv.split() if isinstance(argv, (str, bytes)) else [str(word) for word in argv]
    program = Path(str(words[0])).name if words else ''
    if program in DANGEROUS_PROGRAMS:
        return program
    if program == 'open' and 'Terminal' in words:
        return 'open -a Terminal'
    return None


@pytest.fixture(autouse=True)
def blocked_side_effects(monkeypatch):
    """No test may start a worker, ask for administrator rights, enumerate USB or stop macOS camera
    services. Each attempt is refused and recorded, and fails the test at teardown, because Qt
    prints and swallows an exception raised inside a slot."""
    import subprocess
    import usb.core
    from PySide6 import QtCore
    from camera_runtime import ptpremote
    attempts, real_run = [], subprocess.run

    def refuse(name):
        attempts.append(name)
        raise AssertionError('Forbidden in tests: ' + name)

    def guarded_run(argv, *args, **kwargs):
        name = dangerous(argv)
        return refuse(name) if name else real_run(argv, *args, **kwargs)

    monkeypatch.setattr(QtCore.QProcess, 'start', lambda *a, **k: refuse('starting a worker process'))
    monkeypatch.setattr(usb.core, 'find', lambda *a, **k: refuse('USB enumeration'))
    monkeypatch.setattr(subprocess, 'run', guarded_run)
    # ptpremote binds subprocess.run as a default argument when it is imported.
    monkeypatch.setitem(ptpremote.claim_after_stopping_ptpcamerad.__kwdefaults__, 'run', guarded_run)
    monkeypatch.setattr(ptpremote.running_camera_apps, '__defaults__', (guarded_run,))
    yield attempts
    assert not attempts, 'This test tried: ' + ', '.join(attempts)


@pytest.fixture
def window(tmp_path, monkeypatch):
    """Factory for main windows on a private data folder with QProcess mocked (so no test reaches a
    worker), in the language and platform asked for: window(language='en', platform='win32')."""
    from unittest.mock import Mock, patch
    from PySide6 import QtWidgets as W
    from desktopapp import i18n
    from desktopapp.paths import write_json
    from desktopapp.window import Window
    monkeypatch.setenv('A7C2_DESKTOP_DATA', str(tmp_path / 'data'))
    monkeypatch.setattr('desktopapp.window.QtCore.QProcess', Mock())
    W.QApplication.instance() or W.QApplication([])
    windows = []

    def create(language=None, platform='darwin'):
        if language:
            write_json(tmp_path / 'data/desktop.json', {'language': language})
        with patch('desktopapp.window.sys.platform', platform):
            result = Window()
        result.timer.stop()
        windows.append(result)
        return result
    yield create
    for result in windows:
        result.process = None
        result.close()
    i18n.configure('zh_CN')
