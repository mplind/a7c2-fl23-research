"""Distribution assets a build must not ship without; no camera access."""
import json
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
    assets_check.require(tree(tmp_path), 'public')


def test_the_six_built_in_looks_are_required(tmp_path):
    with pytest.raises(FileNotFoundError, match='six-look'):
        assets_check.require(tree(tmp_path, presets=False), 'public')


def test_the_film_look_library_is_required(tmp_path):
    with pytest.raises(FileNotFoundError, match='prepare_film_looks.py'):
        assets_check.require(tree(tmp_path, film=False), 'public')


def test_the_shutter_sound_library_is_required(tmp_path):
    with pytest.raises(FileNotFoundError, match='prepare_shutter_sounds.py'):
        assets_check.require(tree(tmp_path, sounds=False), 'public')


def test_the_spec_uses_the_check():
    assert 'assets_check.require(root, edition)' in (ROOT / 'dev/desktop/desktop.spec').read_text()


# The personal and public editions ----------------------------------------------------------------------

def personal_assets(root, library=True, pack=True):
    if library:
        folder = root / assets_check.PERSONAL_LIBRARY; folder.mkdir(parents=True)
        (folder / 'catalog.json').write_text('{}')
    if pack:
        folder = root / assets_check.PERSONAL_PACK; folder.mkdir(parents=True)
        (folder / 'pack.json').write_text('{}')
    return root


def test_the_personal_edition_needs_the_personal_assets_and_the_public_one_does_not(tmp_path):
    assets_check.require(tree(tmp_path), 'public')
    with pytest.raises(FileNotFoundError, match='prepare_personal_looks.py.*--edition public'):
        assets_check.require(tmp_path, 'personal')
    personal_assets(tmp_path, pack=False)
    with pytest.raises(FileNotFoundError, match='personal-six-v1'):
        assets_check.require(tmp_path, 'personal')
    personal_assets(tmp_path, library=False)
    assets_check.require(tmp_path, 'personal')
    with pytest.raises(ValueError, match='Unknown edition'):
        assets_check.require(tmp_path, 'release')


def test_the_personal_assets_share_one_root():
    assert assets_check.PERSONAL_ROOT == 'desktop-assets/personal'
    assert assets_check.PERSONAL_LIBRARY == 'desktop-assets/personal/film-looks-v1'
    assert assets_check.PERSONAL_PACK == 'desktop-assets/personal/presets/personal-six-v1'


def test_the_default_edition_is_personal_only_where_the_personal_root_is(tmp_path):
    assert assets_check.default_edition(tree(tmp_path)) == 'public'
    (tmp_path / assets_check.PERSONAL_ROOT).mkdir(parents=True)
    assert assets_check.default_edition(tmp_path) == 'personal'


@pytest.mark.parametrize('relative, personal, sample', [
    ('desktop-assets/personal/film-looks-v1/catalog.json', True, False),
    ('desktop-assets/personal/film-looks-v1/dh-portra400.a7look', True, False),
    ('desktop-assets/personal/film-looks-v1/samples/dh-portra400.jpg', True, True),
    ('desktop-assets/personal/film-looks-v1/samples/dh-portra400.cube', True, False),
    ('desktop-assets/personal/film-looks-v1/dh-portra400.jpg', True, False),
    ('desktop-assets/personal/presets/personal-six-v1/slot1.a7look', True, False),
    ('desktop-assets/personal/presets/personal-six-v1/samples/x.jpg', True, False),
    ('desktop-assets/personal/presets/personal-six-v1.partial/slot1.a7look', True, False),
    ('desktop-assets/personal/anything-else.txt', True, False),
    ('desktop-assets/presets/default-six-v1/slot1.a7look', False, False),
    ('desktop-assets/presets/personal-six-v1/slot1.a7look', False, False),
    ('desktop-assets/personal-old/slot1.a7look', False, False),
    ('desktop-assets/film-looks-v1/samples/portra400.jpg', False, False),
    ('src/desktopapp/presets.py', False, False),
])
def test_personal_assets_are_everything_under_the_personal_root(relative, personal, sample):
    assert assets_check.personal(relative) is personal
    assert assets_check.personal_sample(relative) is sample


@pytest.mark.parametrize('value', [None, '', 'release', 'Personal'])
def test_the_spec_refuses_an_edition_it_does_not_know(monkeypatch, value):
    if value is None:
        monkeypatch.delenv('A7C2_EDITION', raising=False)
    else:
        monkeypatch.setenv('A7C2_EDITION', value)
    with pytest.raises(RuntimeError, match='build.py'):
        assets_check.edition()


@pytest.mark.parametrize('value', ['personal', 'public'])
def test_the_spec_reads_the_edition_build_py_sets(monkeypatch, value):
    monkeypatch.setenv('A7C2_EDITION', value)
    assert assets_check.edition() == value


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
    for name in ('check_identity_regions', 'check_app_icon', 'check_edition'):
        function = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == name)
        assert not [node.lineno for node in ast.walk(function) if isinstance(node, ast.Assert)], name


def test_the_packaged_self_test_fails_without_a_builds_regions_file(monkeypatch):
    import dataclasses
    from looktool import buildprofile
    public, body = buildprofile.BUILDS
    monkeypatch.setattr(buildprofile, 'BUILDS', (public, dataclasses.replace(body, regions_file='factory-regions-missing.json')))
    with pytest.raises(FileNotFoundError, match='factory-regions-missing.json'):
        offline_smoke().check_identity_regions()


# What each edition ships (I1-A: an allow-list) ---------------------------------------------------------

@pytest.mark.parametrize('relative', [
    'desktop-assets/exiftool/exiftool', 'desktop-assets/film-looks-v1/catalog.json',
    'desktop-assets/presets/default-six-v1/slot1.a7look', 'desktop-assets/shutter-sounds-v1/catalog.json',
    'desktop-assets/windows/wdi-simple.exe'])
def test_both_editions_ship_the_known_public_folders(relative):
    assert assets_check.bundled(relative, 'public') and assets_check.bundled(relative, 'personal')


@pytest.mark.parametrize('relative, named', [
    ('desktop-assets/presets/x.partial/slot1.a7look', 'desktop-assets/presets/x.partial'),
    ('desktop-assets/film-looks-v1.partial/catalog.json', 'desktop-assets/film-looks-v1.partial'),
    ('desktop-assets/presets/default-six-v1 copy/slot1.a7look', 'desktop-assets/presets/default-six-v1 copy'),
    ('desktop-assets/presets/personal-six-v1/slot1.a7look', 'desktop-assets/presets/personal-six-v1'),
    ('desktop-assets/notes.txt', 'desktop-assets/notes.txt'),
    ('desktop-assets/film-looks-personal-v1/catalog.json', 'desktop-assets/film-looks-personal-v1'),
])
def test_no_edition_ships_a_folder_it_does_not_know_and_it_names_it(relative, named):
    for edition in assets_check.EDITIONS:
        assert not assets_check.bundled(relative, edition)
        assert assets_check.unlisted(relative, edition) == named


def test_only_the_personal_edition_ships_the_personal_root():
    relative = 'desktop-assets/personal/presets/personal-six-v1/slot1.a7look'
    assert assets_check.bundled(relative, 'personal') and not assets_check.bundled(relative, 'public')
    assert assets_check.unlisted(relative, 'public') == 'desktop-assets/personal'


@pytest.mark.parametrize('edition', ['personal', 'public'])
def test_each_edition_ships_everything_require_demands(edition):
    demanded = assets_check.required(edition)
    assert demanded and all(assets_check.bundled(path, edition) for path, _ in demanded)
    assert any(path.startswith(assets_check.PERSONAL_ROOT) for path, _ in demanded) == (edition == 'personal')


# A built package holds no personal asset (C1-B) ---------------------------------------------------------

def package(root):
    folder = root / 'A7C2Tools.app/Contents/Resources/desktop-assets'
    (folder / 'film-looks-v1').mkdir(parents=True)
    (folder / 'film-looks-v1/catalog.json').write_text('{"schema": "a7c2-film-look-library/1", "looks": []}')
    (folder / 'presets/default-six-v1').mkdir(parents=True)
    (folder / 'presets/default-six-v1/credits.json').write_text('{"pack": "default-six-v1", "looks": []}')
    (root / 'A7C2Tools.app/Contents/Resources/numpy.json').write_text('[1, 2]')
    (root / 'A7C2Tools.app/Contents/Resources/broken.json').write_text('{not json')
    return root / 'A7C2Tools.app'


def test_a_clean_public_package_has_no_personal_findings(tmp_path):
    assert assets_check.personal_findings(package(tmp_path)) == []


@pytest.mark.parametrize('relative, content, found', [
    ('Contents/Resources/desktop-assets/personal/film-looks-v1/look.a7look', 'look',
     'Contents/Resources/desktop-assets/personal'),
    ('Contents/Frameworks/desktop-assets/personal', None, 'Contents/Frameworks/desktop-assets/personal'),
    ('Contents/Resources/elsewhere/pack.json', '{"pack": "personal-six-v1", "looks": []}', None),
    ('Contents/Resources/elsewhere/catalog.json', '{"schema": "x", "personal_use_only": true, "looks": []}', None),
    ('Contents/Resources/elsewhere/manifest.json', '{"personal_use_only": true}', None),
])
def test_a_personal_root_or_marker_anywhere_in_a_package_is_found(tmp_path, relative, content, found):
    app = package(tmp_path)
    path = app / relative
    if content is None:
        path.mkdir(parents=True)
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
    assert assets_check.personal_findings(app) == [found or relative]


# The edition the package records, and the packaged self-test's check of it ------------------------------

def test_the_app_reads_the_edition_its_package_records(tmp_path, monkeypatch):
    from desktopapp import paths
    monkeypatch.setattr(paths, 'EDITION_RECORD', tmp_path / 'edition.json')
    assert paths.edition() is None  # a source tree records none
    for value in assets_check.EDITIONS:
        (tmp_path / 'edition.json').write_text(json.dumps({'edition': value}))
        assert paths.edition() == value
    (tmp_path / 'edition.json').write_text(json.dumps({'edition': 'release'}))
    with pytest.raises(ValueError, match='release'):
        paths.edition()


@pytest.mark.parametrize('edition, pack, library, ok', [
    ('public', 'default-six-v1', 'PUBLIC', True),
    ('public', 'personal-six-v1', 'PUBLIC', False),
    ('public', 'default-six-v1', 'PERSONAL', False),
    ('personal', 'personal-six-v1', 'PERSONAL', True),
    ('personal', 'default-six-v1', 'PERSONAL', False),
])
def test_the_packaged_self_test_checks_the_pack_and_library_of_its_edition(monkeypatch, edition, pack, library, ok):
    from desktopapp import looklibrary, paths, presets
    smoke = offline_smoke('offline_smoke_edition')
    monkeypatch.setattr(paths, 'edition', lambda: edition)
    monkeypatch.setattr(presets, 'active', lambda: pack)
    monkeypatch.setattr(looklibrary, 'location', lambda: getattr(looklibrary, library))
    if ok:
        assert smoke.check_edition() == dict(edition=edition, six_look_pack=pack,
                                             film_library=str(getattr(looklibrary, library)))
    else:
        with pytest.raises(RuntimeError, match='%s package' % edition):
            smoke.check_edition()


def test_a_package_must_record_its_edition_but_a_source_run_need_not(monkeypatch):
    from desktopapp import paths
    smoke = offline_smoke('offline_smoke_edition_source')
    monkeypatch.setattr(paths, 'edition', lambda: None)
    assert smoke.check_edition() == dict(edition='source')
    monkeypatch.setattr(sys, 'frozen', True, raising=False)
    with pytest.raises(RuntimeError, match='does not record its edition'):
        smoke.check_edition()
