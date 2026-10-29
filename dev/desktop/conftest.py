import os
from pathlib import Path
import sys
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'src'), str(ROOT / 'src/looks'), str(ROOT / 'src/looks/tests')]


import pytest

import buildfixtures


@pytest.fixture(scope='module')
def build_fixture_files():
    """Every A7C2_BUILD_FIXTURES program, read once for the module, with its digests (see
    buildfixtures). Skips when the variable is unset."""
    folder = os.environ.get('A7C2_BUILD_FIXTURES')
    if not folder:
        pytest.skip('A7C2_BUILD_FIXTURES is not set')
    return buildfixtures.read(folder)


@pytest.fixture(scope='module')
def build_fixtures(build_fixture_files):
    """The same programs as .public, .body and .hybrid, refused outright when a file isn't the one
    the findings recorded."""
    wrong = buildfixtures.mismatches(build_fixture_files)
    if wrong:
        pytest.fail('A7C2_BUILD_FIXTURES holds other files: ' + '; '.join(wrong), pytrace=False)
    return SimpleNamespace(public=build_fixture_files['public-2.01'], body=build_fixture_files['body-2.01-20250923'],
                           hybrid=build_fixture_files['hybrid-20261027'])


@pytest.fixture(scope='module')
def build_resources(build_fixtures):
    """{build folder name: {name file: bytes}, or None while that build's name files are uncaptured},
    for public-2.01 and body-2.01-20250923 (see buildfixtures.resources). A resources folder missing
    any of nameworker.filenames(), or holding a file without its recorded digest, fails the test."""
    from looktool import nameworker
    folder = os.environ['A7C2_BUILD_FIXTURES']
    try:
        return {name: buildfixtures.resources(folder, name, nameworker.filenames(), buildfixtures.RESOURCE_DIGESTS.get(name))
                for name in buildfixtures.FINDINGS}
    except ValueError as error:
        pytest.fail(str(error), pytrace=False)


@pytest.fixture(autouse=True)
def legacy_chinese_interface(monkeypatch):
    """Existing UI assertions exercise a user retaining the original language."""
    from desktopapp import i18n, window
    monkeypatch.setattr(i18n, '_language', 'zh_CN')
    original = window.load_settings
    monkeypatch.setattr(window, 'load_settings', lambda: {'language': 'zh_CN', **original()})


@pytest.fixture(autouse=True)
def release_widgets():
    """Delete every top-level widget a test leaves behind. Widgets left alive are restyled on every
    application style change and stay connected to the appearance signal, so each test after them
    runs slower (the suite once timed out this way)."""
    from PySide6 import QtCore, QtWidgets
    app = QtWidgets.QApplication.instance()
    before = set(map(id, app.topLevelWidgets())) if app else set()
    yield
    app = QtWidgets.QApplication.instance()
    if app is None:
        return
    for widget in app.topLevelWidgets():
        if id(widget) not in before:
            widget.close()
            widget.deleteLater()
    QtWidgets.QApplication.sendPostedEvents(None, QtCore.QEvent.DeferredDelete)


@pytest.fixture(autouse=True)
def blocked_side_effects(monkeypatch, blocked_programs):
    """No test may start a worker, ask for administrator rights, enumerate USB, stop macOS camera
    services or block on a modal dialog. Each attempt is refused and recorded in the root conftest's
    blocked_programs list, which also refuses the dangerous commands (subprocess.run) and fails the test
    at teardown, because Qt prints and swallows an exception raised inside a slot."""
    import subprocess
    import usb.core
    from PySide6 import QtCore
    from camera_runtime import ptpremote
    attempts, guarded_run = blocked_programs, subprocess.run  # the root conftest's guarded run

    def refuse(name):
        attempts.append(name)
        raise AssertionError('Forbidden in tests: ' + name)

    monkeypatch.setattr(QtCore.QProcess, 'start', lambda *a, **k: refuse('starting a worker process'))
    # An unpatched modal dialog would wait forever for a click offscreen: refuse it instead.
    from PySide6 import QtWidgets
    monkeypatch.setattr(QtWidgets.QDialog, 'exec', lambda *a, **k: refuse('opening a modal dialog'))
    monkeypatch.setattr(QtWidgets.QMessageBox, 'exec', lambda *a, **k: refuse('opening a modal dialog'))
    monkeypatch.setattr(usb.core, 'find', lambda *a, **k: refuse('USB enumeration'))
    # ptpremote binds subprocess.run as a default argument when it is imported.
    monkeypatch.setitem(ptpremote.claim_after_stopping_ptpcamerad.__kwdefaults__, 'run', guarded_run)
    monkeypatch.setattr(ptpremote.running_camera_apps, '__defaults__', (guarded_run,))
    yield attempts


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
        result.close()  # release_widgets then deletes it
    i18n.configure('zh_CN')
