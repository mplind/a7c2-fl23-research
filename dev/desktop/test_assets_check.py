"""Distribution assets a build must not ship without; no camera access."""
from pathlib import Path
import sys
import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'dev/desktop'))
import assets_check
from guihelpers import offline_smoke


def tree(tmp_path, *, presets=True, film=True, sounds=True):
    if presets:
        folder = tmp_path / 'desktop-assets/presets/default-six-v1'; folder.mkdir(parents=True)
        for slot in range(1, 7):
            (folder / ('slot%d.a7look' % slot)).write_text('{}')
    if film:
        folder = tmp_path / 'desktop-assets/film-looks-v1'; folder.mkdir(parents=True)
        (folder / 'catalog.json').write_text('{}')
    if sounds:
        folder = tmp_path / 'desktop-assets/shutter-sounds-v1'; folder.mkdir(parents=True)
        (folder / 'catalog.json').write_text('{}')
    return tmp_path


def test_a_complete_tree_passes(tmp_path):
    assets_check.require(tree(tmp_path))


def test_the_six_built_in_looks_are_required(tmp_path):
    with pytest.raises(FileNotFoundError, match='six-look'):
        assets_check.require(tree(tmp_path, presets=False))


def test_the_film_look_library_is_required(tmp_path):
    with pytest.raises(FileNotFoundError, match='prepare_film_looks.py'):
        assets_check.require(tree(tmp_path, film=False))


def test_the_shutter_sound_library_is_required(tmp_path):
    with pytest.raises(FileNotFoundError, match='prepare_shutter_sounds.py'):
        assets_check.require(tree(tmp_path, sounds=False))


def test_the_spec_uses_the_check():
    assert 'assets_check.require(root)' in (ROOT / 'dev/desktop/desktop.spec').read_text()


def test_the_packaged_self_test_imports_every_new_module_and_loads_the_film_library(monkeypatch, tmp_path):
    smoke = offline_smoke()
    library = ROOT / 'desktop-assets/film-looks-v1'
    if library.is_dir():
        assert smoke.check_feature_modules()['film_looks'] >= 1
    from desktopapp import looklibrary, shuttersounds
    if (ROOT / 'desktop-assets/shutter-sounds-v1').is_dir() and library.is_dir():
        assert smoke.check_feature_modules()['shutter_sounds'] >= 1
    monkeypatch.setattr(shuttersounds, 'location', lambda: tmp_path / 'absent')
    if library.is_dir():
        with pytest.raises(AssertionError, match='shutter sound library'):
            smoke.check_feature_modules()
    monkeypatch.setattr(looklibrary, 'location', lambda: tmp_path / 'absent')
    with pytest.raises(AssertionError, match='film look library'):
        smoke.check_feature_modules()


def test_the_packaged_self_test_imports_the_window_and_its_chrome(monkeypatch):
    import importlib
    smoke = offline_smoke('offline_smoke_imports')
    imported = []
    real = importlib.import_module
    monkeypatch.setattr(smoke.importlib, 'import_module', lambda name, *a: imported.append(name) or real(name, *a))
    try:
        smoke.check_feature_modules()
    except AssertionError:
        pass  # a checkout without the bundled libraries still imports everything first
    for name in ('desktopapp.theme', 'desktopapp.shell', 'desktopapp.window'):
        assert name in imported


def test_the_packaged_self_test_loads_every_builds_identity_regions():
    from looktool import buildprofile
    result = offline_smoke().check_identity_regions()
    assert list(result) == [build.key for build in buildprofile.BUILDS]
    for build in buildprofile.BUILDS:
        rows = buildprofile.identity_regions(build)
        assert result[build.key] == {program: len(found) for program, found in rows.items()}
        assert all(result[build.key].values())


def test_the_packaged_self_test_fails_without_the_vertical_display_files(monkeypatch, tmp_path):
    # buildprofile imports the Vertical Display windows from VERTICAL = parents[2]/'vertical'; a package
    # that leaves them out must fail its self-test, even where verticaltool was already imported.
    from looktool import buildprofile
    monkeypatch.setattr(buildprofile, 'VERTICAL', tmp_path / 'vertical')
    with pytest.raises(RuntimeError, match='Vertical Display'):
        offline_smoke().check_identity_regions()


def test_the_new_self_test_checks_raise_explicitly():
    # R56 Task 9 minor 10: a check that is an assert vanishes under python -O.
    import ast
    tree = ast.parse((ROOT / 'dev/desktop/offline_smoke.py').read_text(encoding='utf-8'))
    for name in ('check_identity_regions', 'check_app_icon'):
        function = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == name)
        assert not [node.lineno for node in ast.walk(function) if isinstance(node, ast.Assert)], name


def test_the_packaged_self_test_fails_without_a_builds_regions_file(monkeypatch):
    import dataclasses
    from looktool import buildprofile
    public, body = buildprofile.BUILDS
    monkeypatch.setattr(buildprofile, 'BUILDS', (public, dataclasses.replace(body, regions_file='factory-regions-missing.json')))
    with pytest.raises(FileNotFoundError, match='factory-regions-missing.json'):
        offline_smoke().check_identity_regions()
