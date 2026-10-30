"""The owner's personal assets: all of them under one root, which git never tracks and only the personal
edition ships; the public edition ships known public folders only. Where this checkout has the personal
assets, they are the bake-off's library and the owner's six, byte for byte. No camera access."""
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
import prepare_personal_looks  # noqa: E402
from packsamples import OWNER_SIX  # noqa: E402

PERSONAL_ROOT = ROOT / assets_check.PERSONAL_ROOT
LIBRARY = ROOT / assets_check.PERSONAL_LIBRARY
PACK = ROOT / assets_check.PERSONAL_PACK
HAS_LIBRARY = (LIBRARY / 'catalog.json').is_file()
HAS_PACK = (PACK / 'pack.json').is_file()


def git(*args, **options):
    return subprocess.run(['git', *args], cwd=ROOT, capture_output=True, text=True, **options)


IN_GIT = pytest.mark.skipif(git('rev-parse', '--is-inside-work-tree').stdout.strip() != 'true',
                            reason='a source tree outside git')


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def test_the_app_and_the_build_keep_every_personal_asset_under_one_root():
    assert ROOT / assets_check.PERSONAL_LIBRARY == looklibrary.PERSONAL
    assert ROOT / assets_check.PERSONAL_PACK == presets.folder(presets.PERSONAL)
    assert prepare_personal_looks.LIBRARY == looklibrary.PERSONAL
    assert prepare_personal_looks.PACK == presets.folder(presets.PERSONAL)
    assert all(assets_check.personal(folder + '/x') for folder in assets_check.PERSONAL)
    assert not any(assets_check.personal(folder + '/x') for folder in assets_check.PUBLIC_ASSETS)


# Never in git (I2) -------------------------------------------------------------------------------------

@IN_GIT
def test_git_tracks_nothing_under_the_personal_root():
    assert git('ls-files', '--', assets_check.PERSONAL_ROOT).stdout == ''


@IN_GIT
def test_git_ignores_every_file_under_the_personal_root():
    found = sorted(path.relative_to(ROOT).as_posix() for path in PERSONAL_ROOT.rglob('*') if path.is_file())
    # Paths that need not exist yet, so the rule holds on a checkout without the assets too.
    probes = [assets_check.PERSONAL_ROOT + '/' + name for name in (
        'notes.txt', 'film-looks-v1/catalog.json', 'film-looks-v1/samples/a look.jpg',
        'presets/personal-six-v1/pack.json', 'presets/personal-six-v1/slot1.a7look', 'presets/x.partial/slot1.a7look')]
    paths = found + probes
    result = git('check-ignore', '--stdin', '-z', input='\0'.join(paths) + '\0')
    assert sorted(path for path in result.stdout.split('\0') if path) == sorted(paths)


def test_every_folder_marked_personal_use_only_is_under_the_personal_root():
    """A catalog, pack or manifest under desktop-assets/ that declares personal_use_only must sit under the
    personal root: anywhere else the public edition would never ship it, but a public asset folder must not
    hold one at all."""
    marked = set()
    for path in sorted((ROOT / 'desktop-assets').rglob('*.json')):
        if path.name not in ('catalog.json', 'pack.json', 'manifest.json'):
            continue
        try:
            document = json.loads(path.read_text(encoding='utf-8'))
        except ValueError:
            continue
        if isinstance(document, dict) and document.get('personal_use_only'):
            marked.add(path.relative_to(ROOT).as_posix())
    assert {path for path in marked if not assets_check.personal(path)} == set()


# What desktop.spec collects (C1-B, I1-A) ------------------------------------------------------------------

def run_spec(monkeypatch, tmp_path, root, edition, capsys):
    """(data files as (path from `root`, destination), printed output, the edition record) of
    dev/desktop/desktop.spec for `edition` on the checkout at `root`, with PyInstaller and the packaging
    steps that choose no files stubbed out."""
    hooks = ModuleType('PyInstaller.utils.hooks')
    hooks.collect_all = lambda package: ([], [], [])
    for name, module in (('PyInstaller', ModuleType('PyInstaller')), ('PyInstaller.utils', ModuleType('PyInstaller.utils')),
                         ('PyInstaller.utils.hooks', hooks),
                         ('profilepack', SimpleNamespace(files=lambda: {})),
                         ('machosign', SimpleNamespace(keep_unsigned=lambda binaries, datas: (binaries, datas)))):
        monkeypatch.setitem(sys.modules, name, module)
    monkeypatch.setattr(sys, 'path', list(sys.path))  # the spec puts its dev/desktop first
    monkeypatch.setenv('A7C2_EDITION', edition)
    collected = {}

    def analysis(scripts, **options):
        collected['datas'] = options['datas']
        return SimpleNamespace(binaries=[], datas=options['datas'], pure=[], scripts=[])
    stub = lambda *args, **kwargs: None  # noqa: E731
    spec = ROOT / 'dev/desktop/desktop.spec'
    work = tmp_path / ('work-' + edition)
    work.mkdir()
    capsys.readouterr()
    exec(compile(spec.read_text(encoding='utf-8'), str(spec), 'exec'),
         dict(SPECPATH=str(root / 'dev/desktop'), workpath=str(work), Analysis=analysis, PYZ=stub, EXE=stub,
              COLLECT=stub, BUNDLE=stub))
    record = work / 'edition.json'
    datas = set()
    for source, folder in collected['datas']:
        path = Path(source).resolve()
        if path == record.resolve():
            assert folder == '.'
            continue
        if path.is_relative_to(root.resolve()):
            datas.add((path.relative_to(root.resolve()).as_posix(), folder))
    assert (str(record), '.') in collected['datas']
    return datas, capsys.readouterr().out, json.loads(record.read_text(encoding='utf-8'))


def checkout(root):
    """A small checkout: the public assets require() demands, the personal root, and folders no edition
    knows (a staging copy, a Finder copy, a leftover of the old personal layout)."""
    files = {'src/desktopapp/__init__.py': "VERSION = '0.0.1'\n",
             'desktop-assets/film-looks-v1/catalog.json': '{}', 'desktop-assets/shutter-sounds-v1/catalog.json': '{}',
             'desktop-assets/exiftool/exiftool': 'tool',
             'desktop-assets/personal/film-looks-v1/catalog.json': '{"personal_use_only": true}',
             'desktop-assets/personal/film-looks-v1/look.a7look': 'look',
             'desktop-assets/personal/film-looks-v1/samples/look.jpg': 'jpeg',
             'desktop-assets/personal/presets/personal-six-v1/pack.json': '{"pack": "personal-six-v1"}',
             'desktop-assets/presets/x.partial/slot1.a7look': 'staged',
             'desktop-assets/presets/default-six-v1 copy/slot1.a7look': 'copied',
             'desktop-assets/presets/personal-six-v1/slot1.a7look': 'old layout'}
    files.update({'desktop-assets/presets/default-six-v1/slot%d.a7look' % slot: 'public' for slot in range(1, 7)})
    for relative, text in files.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding='utf-8')
    return root


UNKNOWN = ('desktop-assets/presets/default-six-v1 copy', 'desktop-assets/presets/personal-six-v1',
           'desktop-assets/presets/x.partial')


def test_the_public_edition_ships_only_known_public_folders_and_names_the_rest(monkeypatch, tmp_path, capsys):
    root = checkout(tmp_path / 'checkout')
    datas, printed, record = run_spec(monkeypatch, tmp_path, root, 'public', capsys)
    assets = sorted(path for path, _ in datas if path.startswith('desktop-assets/'))
    assert assets == ['desktop-assets/exiftool/exiftool', 'desktop-assets/film-looks-v1/catalog.json'] + [
        'desktop-assets/presets/default-six-v1/slot%d.a7look' % slot for slot in range(1, 7)] + [
        'desktop-assets/shutter-sounds-v1/catalog.json']
    assert record == {'edition': 'public'}
    assert 'Left out of this public package (not a known asset folder): ' + ', '.join(
        sorted(('desktop-assets/personal',) + UNKNOWN)) in printed


def test_the_personal_edition_adds_the_personal_root_and_nothing_unknown(monkeypatch, tmp_path, capsys):
    root = checkout(tmp_path / 'checkout')
    public, _, _ = run_spec(monkeypatch, tmp_path, root, 'public', capsys)
    personal, printed, record = run_spec(monkeypatch, tmp_path, root, 'personal', capsys)
    assert sorted(path for path, _ in personal - public) == [
        'desktop-assets/personal/film-looks-v1/catalog.json', 'desktop-assets/personal/film-looks-v1/look.a7look',
        'desktop-assets/personal/film-looks-v1/samples/look.jpg',
        'desktop-assets/personal/presets/personal-six-v1/pack.json']
    assert record == {'edition': 'personal'}
    assert 'Left out of this personal package (not a known asset folder): ' + ', '.join(sorted(UNKNOWN)) in printed


@pytest.mark.skipif(not (HAS_LIBRARY and HAS_PACK), reason="the owner's personal assets are personal")
def test_on_this_checkout_only_the_personal_edition_ships_the_personal_root(monkeypatch, tmp_path, capsys):
    public, _, _ = run_spec(monkeypatch, tmp_path, ROOT, 'public', capsys)
    personal, _, _ = run_spec(monkeypatch, tmp_path, ROOT, 'personal', capsys)
    expected = {(path.relative_to(ROOT).as_posix(), path.parent.relative_to(ROOT).as_posix())
                for path in sorted(PERSONAL_ROOT.rglob('*')) if path.is_file()}
    assert [path for path, _ in public if assets_check.personal(path)] == []
    assert {row for row in personal - public if row[0].startswith('desktop-assets/')} == expected
    assert any(path.endswith('.jpg') for path, _ in expected)


# Where this checkout has them: the bake-off's library and the owner's six ------------------------------

def manifest():
    return json.loads((LIBRARY / 'manifest.json').read_text(encoding='utf-8'))


@pytest.mark.skipif(not HAS_LIBRARY, reason="the owner's personal library is a personal asset")
def test_the_personal_library_lists_exactly_the_manifests_looks_byte_for_byte():
    document = manifest()
    assert document['personal_use_only'] is True
    looks = looklibrary.catalog(LIBRARY)
    assert [look['id'] for look in looks] == [look['id'] for look in document['looks']]
    assert len(looks) == 10
    for look, row in zip(looks, document['looks']):
        assert sha(look['path']) == row['sha256'] and look['name'] == row['camera_name']
        assert look['shareable'] is False and look['source']['url'].startswith('https://')
        assert look['notes'].startswith(prepare_personal_looks.rationale(row['why_included']))
        assert 'Fit: MAE' not in look['notes']  # the dialog shows the fit itself
        assert ('stop dark' in look['notes']) == (row['exposure_comp_thirds'] > 0)
    assert json.loads((LIBRARY / 'catalog.json').read_text(encoding='utf-8'))['personal_use_only'] is True
    assert looklibrary.location() == LIBRARY


@pytest.mark.skipif(not (HAS_PACK and HAS_LIBRARY), reason="the owner's personal pack is a personal asset")
def test_the_personal_pack_resolves_to_the_owners_six_in_order():
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
