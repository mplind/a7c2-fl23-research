"""The owner's personal assets: git never tracks them, only the personal edition bundles them, and, where
this checkout has them, they are the bake-off's library and his six, byte for byte. No camera access."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from types import ModuleType, SimpleNamespace

import pytest

from desktopapp import looklibrary, presets

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'dev/desktop'))
import assets_check  # noqa: E402

LIBRARY = ROOT / assets_check.PERSONAL_LIBRARY
PACK = ROOT / assets_check.PERSONAL_PACK
HAS_LIBRARY = (LIBRARY / 'catalog.json').is_file()
HAS_PACK = (PACK / 'pack.json').is_file()
# The owner's six, Custom 1–6, as he chose them on 29 Oct 2026.
OWNER_SIX = ('Portra 400 (Dehancer)', 'Classic Chrome', 'Kodachrome 64 (Dehancer)', 'Velvia 50 (Dehancer)',
             'CineStill 800T (Dehancer)', 'Portra 160 NC (DxO)')


def git(*args):
    return subprocess.run(['git', *args], cwd=ROOT, capture_output=True, text=True)


IN_GIT = git('rev-parse', '--is-inside-work-tree').stdout.strip() == 'true'


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def test_the_app_and_the_build_name_the_same_personal_assets():
    assert ROOT / assets_check.PERSONAL_LIBRARY == looklibrary.PERSONAL
    assert assets_check.PERSONAL_PACK == 'desktop-assets/presets/' + presets.PERSONAL
    assert assets_check.PERSONAL == (assets_check.PERSONAL_LIBRARY, assets_check.PERSONAL_PACK)


# Never in git ------------------------------------------------------------------------------------------

@pytest.mark.skipif(not IN_GIT, reason='a source tree outside git')
def test_git_tracks_no_look_under_desktop_assets():
    tracked = git('ls-files', '--', 'desktop-assets').stdout.split()
    assert [path for path in tracked if path.endswith('.a7look')] == []


@pytest.mark.skipif(not IN_GIT, reason='a source tree outside git')
@pytest.mark.parametrize('folder', assets_check.PERSONAL)
def test_git_ignores_both_personal_folders(folder):
    for path in (folder, folder + '/slot1.a7look', folder + '/catalog.json', folder + '/samples/look.jpg'):
        assert git('check-ignore', '-q', path).returncode == 0, path


def test_every_folder_marked_personal_use_only_is_a_personal_asset():
    """A new folder under desktop-assets/ that declares personal_use_only must be listed in
    assets_check.PERSONAL, or a public build would bundle it."""
    marked = set()
    for path in sorted((ROOT / 'desktop-assets').rglob('*.json')):
        if path.name not in ('catalog.json', 'pack.json', 'manifest.json'):
            continue
        try:
            document = json.loads(path.read_text(encoding='utf-8'))
        except ValueError:
            continue
        if isinstance(document, dict) and document.get('personal_use_only'):
            marked.add(path.parent.relative_to(ROOT).as_posix())
    assert {folder for folder in marked if not assets_check.personal(folder + '/x')} == set()


# Only the personal edition bundles them ---------------------------------------------------------------

def spec_datas(monkeypatch, edition):
    """The data files desktop.spec collects for `edition`, (source, destination folder) pairs, from this
    checkout, with PyInstaller and the packaging steps that do not choose files stubbed out."""
    hooks = ModuleType('PyInstaller.utils.hooks')
    hooks.collect_all = lambda package: ([], [], [])
    for name, module in (('PyInstaller', ModuleType('PyInstaller')), ('PyInstaller.utils', ModuleType('PyInstaller.utils')),
                         ('PyInstaller.utils.hooks', hooks),
                         ('profilepack', SimpleNamespace(files=lambda: {})),
                         ('machosign', SimpleNamespace(keep_unsigned=lambda binaries, datas: (binaries, datas)))):
        monkeypatch.setitem(sys.modules, name, module)
    monkeypatch.setenv('A7C2_EDITION', edition)
    collected = {}

    def analysis(scripts, **options):
        collected['datas'] = options['datas']
        return SimpleNamespace(binaries=[], datas=options['datas'], pure=[], scripts=[])
    stub = lambda *args, **kwargs: None  # noqa: E731
    spec = ROOT / 'dev/desktop/desktop.spec'
    exec(compile(spec.read_text(encoding='utf-8'), str(spec), 'exec'),
         dict(SPECPATH=str(spec.parent), Analysis=analysis, PYZ=stub, EXE=stub, COLLECT=stub, BUNDLE=stub))
    return {(Path(source).resolve().relative_to(ROOT).as_posix(), folder) for source, folder in collected['datas']
            if Path(source).resolve().is_relative_to(ROOT)}


def personal_files():
    return {(path.relative_to(ROOT).as_posix(), path.parent.relative_to(ROOT).as_posix())
            for folder in assets_check.PERSONAL for path in sorted((ROOT / folder).rglob('*')) if path.is_file()}


@pytest.mark.skipif(not (HAS_LIBRARY and HAS_PACK), reason="The owner's personal assets are personal")
def test_only_the_personal_edition_bundles_the_personal_assets(monkeypatch):
    public = spec_datas(monkeypatch, 'public')
    personal = spec_datas(monkeypatch, 'personal')
    assert [source for source, _ in public if assets_check.personal(source)] == []
    assert personal - public == personal_files()  # every personal file, samples included, and nothing else
    assert public <= personal
    assert any(source.endswith('.jpg') for source, _ in personal_files())


# Where this checkout has them: the bake-off's library and the owner's six ---------------------------------

def manifest():
    return json.loads((LIBRARY / 'manifest.json').read_text(encoding='utf-8'))


@pytest.mark.skipif(not HAS_LIBRARY, reason="The owner's personal library is a personal asset")
def test_the_personal_library_lists_exactly_the_manifests_looks_byte_for_byte():
    document = manifest()
    assert document['personal_use_only'] is True
    looks = looklibrary.catalog(LIBRARY)
    assert [look['id'] for look in looks] == [look['id'] for look in document['looks']]
    assert len(looks) == 10
    for look, row in zip(looks, document['looks']):
        assert sha(look['path']) == row['sha256'] and look['name'] == row['camera_name']
        assert look['shareable'] is False and look['source']['url'].startswith('https://')
        assert look['notes'].startswith(row['why_included'])
        assert ('stop dark' in look['notes']) == (row['exposure_comp_thirds'] > 0)
    assert json.loads((LIBRARY / 'catalog.json').read_text(encoding='utf-8'))['personal_use_only'] is True
    assert looklibrary.location() == LIBRARY


@pytest.mark.skipif(not (HAS_PACK and HAS_LIBRARY), reason="The owner's personal pack is a personal asset")
def test_the_personal_pack_resolves_to_prices_six_in_his_order():
    assert presets.active() == presets.PERSONAL
    resolved = presets.resolve(dict(preset_pack=presets.PERSONAL))
    assert [(row['slot'], row['name']) for row in resolved['looks']] == list(enumerate(OWNER_SIX, 1))
    by_id = {row['id']: row for row in manifest()['looks']}
    document = json.loads((PACK / 'pack.json').read_text(encoding='utf-8'))
    assert document['personal_use_only'] is True
    for row, saved in zip(resolved['looks'], document['looks']):
        source = by_id[saved['library_id']]
        assert source['default_slot'] == row['slot'] and source['camera_name'] == row['name']
        assert Path(row['path']).read_bytes() == (LIBRARY / (source['id'] + '.a7look')).read_bytes()
        assert sha(row['path']) == source['sha256'] == saved['sha256']
        assert saved['exposure_comp_thirds'] == source['exposure_comp_thirds']
    assert presets.load(presets.PERSONAL).dark == (
        ('Portra 400 (Dehancer)', 2), ('Kodachrome 64 (Dehancer)', 1), ('Velvia 50 (Dehancer)', 1),
        ('CineStill 800T (Dehancer)', 1))
