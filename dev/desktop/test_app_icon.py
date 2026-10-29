"""The app icon: one AppIcon.icns for the bundle, the Dock and the window, in the source and the package."""
import ast
import importlib.util
import os
from pathlib import Path

import pytest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6 import QtWidgets as W  # noqa: E402

from desktopapp import paths, window  # noqa: E402
from guihelpers import offline_smoke  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
SPEC = ast.parse((ROOT / 'dev/desktop/desktop.spec').read_text(encoding='utf-8'))


def relative_icon():
    return paths.APP_ICON.relative_to(paths.ROOT).as_posix()


def spec_call(name):
    return next(node for node in ast.walk(SPEC)
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == name)


def test_the_app_icon_is_the_repo_copy_beside_the_build_files():
    assert paths.APP_ICON == ROOT / 'dev/desktop/icon/AppIcon.icns'
    assert paths.APP_ICON.read_bytes()[:4] == b'icns'
    assert (ROOT / 'dev/desktop/icon/make_icon.py').is_file()


def assigned(name):
    return next(node.value for node in ast.walk(SPEC) if isinstance(node, ast.Assign)
                and [ast.unparse(target) for target in node.targets] == [name])


def test_the_spec_names_the_icon_once():
    # R56 Task 9 minor 5: one ICON path, used by the EXE/BUNDLE icon and by the data files.
    assert ast.literal_eval(assigned('ICON')) == relative_icon()
    source = (ROOT / 'dev/desktop/desktop.spec').read_text(encoding='utf-8')
    assert source.count(relative_icon()) == 1


def test_the_spec_gives_the_executable_and_the_bundle_the_app_icon():
    assert ast.unparse(assigned('icon')) == 'str(root / ICON)'
    for name in ('EXE', 'BUNDLE'):
        keyword = next((k for k in spec_call(name).keywords if k.arg == 'icon'), None)
        assert keyword is not None and ast.unparse(keyword.value) == 'icon', name


def test_the_package_ships_the_icon_where_the_window_loads_it():
    # The frozen app's ROOT holds the listed files at their source paths, so paths.APP_ICON resolves there.
    listed = next(node.iter for node in ast.walk(SPEC) if isinstance(node, ast.For)
                  and isinstance(node.iter, ast.Tuple) and any(isinstance(item, ast.Constant)
                  and item.value == 'desktop.py' for item in node.iter.elts))
    assert 'ICON' in [ast.unparse(item) for item in listed.elts]


@pytest.fixture
def app():
    app = W.QApplication.instance() or W.QApplication([])
    before = (app.windowIcon(), app.applicationName(), app.applicationVersion(), app.organizationName())
    yield app
    icon, name, version, organization = before
    app.setWindowIcon(icon)
    app.setApplicationName(name)
    app.setApplicationVersion(version)
    app.setOrganizationName(organization)


def test_the_dock_and_the_window_show_the_app_icon(app):
    window.configure_application(app)
    icon = app.windowIcon()
    assert not icon.isNull()
    assert set(smoke().APP_ICON_SIZES) <= {size.width() for size in icon.availableSizes()}
    assert (app.applicationName(), app.organizationName()) == ('A7C2Tools', 'QAQLeonard')


def smoke():
    return offline_smoke('offline_smoke_icon')


def test_the_packaged_self_test_reads_the_app_icon():
    module = smoke()
    assert set(module.APP_ICON_SIZES) <= set(module.check_app_icon()['sizes'])


def test_the_packaged_self_test_fails_without_the_app_icon(monkeypatch, tmp_path):
    monkeypatch.setattr(paths, 'APP_ICON', tmp_path / 'AppIcon.icns')
    with pytest.raises(RuntimeError, match='app icon'):
        smoke().check_app_icon()


# make_icon.py (R56 Task 9 minor 8) -----------------------------------------------------------------

def make_icon():
    spec = importlib.util.spec_from_file_location('make_icon_under_test', ROOT / 'dev/desktop/icon/make_icon.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_icon_drawing_is_one_svg_page_of_its_stated_size():
    icon = make_icon()
    text = icon.svg()
    from xml.etree import ElementTree
    root = ElementTree.fromstring(text)
    assert root.tag.endswith('svg') and (root.get('width'), root.get('height')) == (str(icon.W), str(icon.H))


def child(code):
    import subprocess
    import sys
    return subprocess.Popen([sys.executable, '-I', '-c', code], start_new_session=True)


def test_stopping_chrome_ends_its_group():
    process = child('import time; time.sleep(60)')
    make_icon().stop(process, grace=5)
    assert process.returncode is not None


def test_stopping_chrome_falls_back_to_sigkill():
    import time
    process = child('import signal, sys, time; signal.signal(signal.SIGTERM, signal.SIG_IGN); '
                    'print("ready", flush=True); time.sleep(60)')
    time.sleep(0.5)  # SIGTERM ignored from here on
    started = time.monotonic()
    make_icon().stop(process, grace=1)
    assert process.returncode == -9 and time.monotonic() - started < 10


def test_stopping_chrome_that_has_already_exited_is_quiet():
    # Its group then holds only the unreaped leader: killpg fails with EPERM on macOS, ESRCH elsewhere.
    import time
    process = child('pass')
    time.sleep(0.5)
    make_icon().stop(process, grace=5)
    assert process.returncode == 0
