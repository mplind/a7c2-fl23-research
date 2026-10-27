"""Distribution assets a build must not ship without; no camera access."""
from pathlib import Path
import sys
import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'dev/desktop'))
import assets_check


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
    import importlib.util
    spec = importlib.util.spec_from_file_location('offline_smoke_under_test', ROOT / 'dev/desktop/offline_smoke.py')
    smoke = importlib.util.module_from_spec(spec); spec.loader.exec_module(smoke)
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
    import importlib, importlib.util
    spec = importlib.util.spec_from_file_location('offline_smoke_imports', ROOT / 'dev/desktop/offline_smoke.py')
    smoke = importlib.util.module_from_spec(spec); spec.loader.exec_module(smoke)
    imported = []
    real = importlib.import_module
    monkeypatch.setattr(smoke.importlib, 'import_module', lambda name, *a: imported.append(name) or real(name, *a))
    try:
        smoke.check_feature_modules()
    except AssertionError:
        pass  # a checkout without the bundled libraries still imports everything first
    for name in ('desktopapp.theme', 'desktopapp.shell', 'desktopapp.window'):
        assert name in imported
