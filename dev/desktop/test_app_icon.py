"""The app icon: one AppIcon.icns for the bundle, the Dock and the window, in the source and the package."""
import ast
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


def test_the_spec_gives_the_executable_and_the_bundle_the_app_icon():
    assigned = next(node.value for node in ast.walk(SPEC) if isinstance(node, ast.Assign)
                    and [ast.unparse(target) for target in node.targets] == ['icon'])
    assert ast.unparse(assigned) == "str(root / '%s')" % relative_icon()
    for name in ('EXE', 'BUNDLE'):
        keyword = next((k for k in spec_call(name).keywords if k.arg == 'icon'), None)
        assert keyword is not None and ast.unparse(keyword.value) == 'icon', name


def test_the_package_ships_the_icon_where_the_window_loads_it():
    # The frozen app's ROOT holds the listed files at their source paths, so paths.APP_ICON resolves there.
    listed = next(node.iter for node in ast.walk(SPEC) if isinstance(node, ast.For)
                  and isinstance(node.iter, ast.Tuple) and any(isinstance(item, ast.Constant)
                  and item.value == 'desktop.py' for item in node.iter.elts))
    assert relative_icon() in [item.value for item in listed.elts]


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
    with pytest.raises(AssertionError, match='app icon'):
        smoke().check_app_icon()
