"""Preparing the owner's personal film library and six-look pack from the bake-off's library: byte-for-byte
copies checked against the manifest, catalog entries with their rationale and exposure note, and refusals
that leave the previous assets in place. A fixture library stands in for the real one; no camera access."""
import hashlib
import json
from pathlib import Path
import sys
from unittest.mock import patch

import pytest

from desktopapp import looklibrary, presets

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'dev/desktop'))
import assets_check  # noqa: E402
import prepare_personal_looks as personal  # noqa: E402
from looksamples import look_file  # noqa: E402
from packsamples import OWNER_SIX as SIX  # noqa: E402

DEHANCER_LICENCE = 'Personal use only — converted from a purchased Dehancer licence; not for distribution'
DXO_LICENCE = 'Personal use only — converted from a purchased DxO licence; not for distribution'
BUNDLED_LICENCE = 'Already bundled with A7C II Tools (its attribution: owner-supplied DCP, MIT). Fujifilm-derived.'


def look(id, name, stock, source, slot=None, thirds=0, sim=False, why='Why it made the cut.'):
    app = {'dehancer': 'Dehancer Desktop 1.1.0', 'dxo': 'DxO FilmPack 8.6.0',
           'fujifilm-bundled': 'the Fujifilm-style look bundled with A7C II Tools'}[source]
    licence = BUNDLED_LICENCE if source == 'fujifilm-bundled' else 'Personal use only: converted from %s.' % app
    return dict(id=id, stock=stock, camera_name=name, label=name, source=source, source_app=app, sim=sim,
                file='looks/%s.a7look' % id, default_slot=slot, exposure_comp_thirds=thirds,
                exposure_comp='+%d/3 EV' % thirds if thirds else 'none', why_included=why, licence=licence)


LOOKS = [
    look('dh-kodachrome64', 'Kodachrome 64 (Dehancer)', 'Kodachrome', 'dehancer', slot=3, thirds=1,
         why='The closest to Kodachrome.'),
    look('dxo-kodachrome64generic', 'Kodachrome 64 generic (DxO)', 'Kodachrome', 'dxo'),
    look('dh-velvia50', 'Velvia 50 (Dehancer)', 'Velvia', 'dehancer', slot=4, thirds=1),
    look('dh-portra400', 'Portra 400 (Dehancer)', 'Portra 400', 'dehancer', slot=1, thirds=2,
         why='Skin first. Fit: MAE 1.26 / P95 4.03, within the median bundled look (2.39 / 8.02).'),
    look('dxo-portra160nc', 'Portra 160 NC (DxO)', 'Portra 160 NC', 'dxo', slot=6,
         why='Natural, as NC was. Fit: MAE 1.59 / P95 5.72, within the median bundled look (2.39 / 8.02).'),
    look('dh-cinestill800t', 'CineStill 800T (Dehancer)', 'CineStill 800T', 'dehancer', slot=5, thirds=1),
    look('fujifilm-bundled-classicchrome', 'Classic Chrome', 'Classic Chrome', 'fujifilm-bundled', slot=2, sim=True),
    look('dxo-eterna', 'Eterna sim (DxO)', 'Eterna', 'dxo', sim=True),
]


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def library(tmp_path, looks=LOOKS, folder='personal-library', **manifest):
    """A bake-off library: looks/, samples/, writeups/, its guides and a manifest with checksums."""
    source = tmp_path / folder
    (source / 'looks').mkdir(parents=True)
    for name in ('samples', 'writeups'):
        (source / name).mkdir()
    rows = []
    for row in looks:
        path = source / row['file']
        if not path.exists():
            look_file(path, mae=1.5, p95=5.0, name=row['camera_name'])
            document = json.loads(path.read_text(encoding='utf-8'))
            document['method'] = ('Lightroom-reference-native-four-stage-extended-v1'
                                  if row['source'] == 'fujifilm-bundled' else 'CUBE-measured-native-four-stage-v1')
            path.write_text(json.dumps(document), encoding='utf-8')
        rows.append(dict(row, sha256=row.get('sha256') or sha(path)))
        (source / 'samples' / (row['id'] + '.jpg')).write_bytes(b'jpeg ' + row['id'].encode())
        (source / 'writeups' / (row['id'] + '.md')).write_text('# ' + row['camera_name'])
    for name in ('README.md', 'GUIDE.html', 'HOW-TO-ADD-A-STOCK.md'):
        (source / name).write_text(name)
    document = dict(dict(name='A7C II personal film library', personal_use_only=True, looks=rows), **manifest)
    (source / 'manifest.json').write_text(json.dumps(document, ensure_ascii=False), encoding='utf-8')
    return source


@pytest.fixture
def checked_slots():
    """presets.check_slot as the prepared pack calls it; the fixture looks carry no photo stage."""
    with patch.object(presets, 'check_slot') as check:
        yield check


def prepare(tmp_path, source):
    return personal.prepare(source, tmp_path / 'film-looks-personal-v1', tmp_path / 'personal-six-v1')


def test_the_targets_are_the_personal_assets_the_app_and_the_build_know():
    assert personal.LIBRARY == ROOT / assets_check.PERSONAL_LIBRARY
    assert personal.PACK == ROOT / assets_check.PERSONAL_PACK
    assert personal.PACK == presets.folder(presets.PERSONAL)
    assert personal.LIBRARY == looklibrary.PERSONAL
    assert all(path.is_relative_to(ROOT / assets_check.PERSONAL_ROOT) for path in (personal.LIBRARY, personal.PACK))


# The library ----------------------------------------------------------------------------------------

def test_every_look_is_copied_byte_for_byte_and_catalogued_in_manifest_order(tmp_path, checked_slots):
    source = library(tmp_path)
    entries, _ = prepare(tmp_path, source)
    target = tmp_path / 'film-looks-personal-v1'
    assert [entry['id'] for entry in entries] == [row['id'] for row in LOOKS]
    for row in LOOKS:
        assert (target / (row['id'] + '.a7look')).read_bytes() == (source / row['file']).read_bytes()
    catalog = json.loads((target / 'catalog.json').read_text(encoding='utf-8'))
    assert catalog['schema'] == looklibrary.SCHEMA and catalog['personal_use_only'] is True
    assert [look['id'] for look in looklibrary.catalog(target)] == [row['id'] for row in LOOKS]


def test_each_entry_names_its_source_licence_and_rationale(tmp_path, checked_slots):
    entries = {entry['id']: entry for entry in prepare(tmp_path, library(tmp_path))[0]}
    portra = entries['dh-portra400']
    assert portra['name'] == 'Portra 400 (Dehancer)' and portra['kind'] == 'negative'
    assert entries['dxo-eterna']['notes'] == 'Why it made the cut.'  # no fit sentence, nothing dropped
    assert portra['file'] == 'dh-portra400.a7look' and portra['shareable'] is False
    assert portra['source'] == dict(project='Dehancer Desktop 1.1.0', author='Dehancer',
                                    url='https://www.dehancer.com/', licence=DEHANCER_LICENCE)
    assert portra['modification'] == ('Rendered through Dehancer Desktop 1.1.0 from an identity image, made '
                                      'into a CUBE LUT and fitted to the A7C II look table')
    assert portra['notes'] == 'Skin first. Portra 400 (Dehancer) renders about ⅔ stop dark; add +⅔ EV.'
    assert entries['dxo-portra160nc']['notes'] == 'Natural, as NC was.'  # its fit sentence dropped
    assert entries['dh-kodachrome64']['notes'] == ('The closest to Kodachrome. Kodachrome 64 (Dehancer) renders '
                                                   'about ⅓ stop dark; add +⅓ EV.')
    assert entries['dh-kodachrome64']['kind'] == 'slide' and entries['dh-cinestill800t']['kind'] == 'cine'
    generic = entries['dxo-kodachrome64generic']
    assert generic['notes'] == 'Why it made the cut.'  # no exposure note for a look that needs none
    assert generic['source'] == dict(project='DxO FilmPack 8.6.0', author='DxO',
                                     url='https://www.dxo.com/dxo-filmpack/', licence=DXO_LICENCE)
    assert entries['dxo-eterna']['kind'] == 'style'  # a Fujifilm simulation is a style, not a film
    assert all(entry['shareable'] is False and len(entry['swatches']) == len(looklibrary.REFERENCE)
               for entry in entries.values())


def test_the_bundled_classic_chrome_keeps_its_own_licence(tmp_path, checked_slots):
    chrome = {entry['id']: entry for entry in prepare(tmp_path, library(tmp_path))[0]}['fujifilm-bundled-classicchrome']
    assert chrome['name'] == 'Classic Chrome' and chrome['kind'] == 'style' and chrome['shareable'] is False
    assert chrome['source'] == dict(project='the Fujifilm-style look bundled with A7C II Tools',
                                    author='门萨特里顿 (MTriton)',
                                    url='https://github.com/QAQLeonard/a7c2-fl23-research', licence=BUNDLED_LICENCE)
    assert chrome['modification'] == 'Fitted from its DCP profile to the A7C II look table, as A7C II Tools bundles it'


def test_the_guides_samples_and_write_ups_sit_beside_the_looks(tmp_path, checked_slots):
    source = library(tmp_path)
    prepare(tmp_path, source)
    target = tmp_path / 'film-looks-personal-v1'
    for name in ('README.md', 'GUIDE.html', 'HOW-TO-ADD-A-STOCK.md', 'manifest.json'):
        assert (target / name).read_bytes() == (source / name).read_bytes()
    for folder in ('samples', 'writeups'):
        assert sorted(path.name for path in (target / folder).iterdir()) == \
            sorted(path.name for path in (source / folder).iterdir())


# The six-look pack ----------------------------------------------------------------------------------

def test_the_pack_holds_the_six_default_slots_in_order(tmp_path, checked_slots):
    source = library(tmp_path)
    _, rows = prepare(tmp_path, source)
    pack = tmp_path / 'personal-six-v1'
    by_id = {row['id']: row for row in LOOKS}
    document = json.loads((pack / 'pack.json').read_text(encoding='utf-8'))
    assert document['pack'] == presets.PERSONAL and document['personal_use_only'] is True
    assert document['notice'] == personal.NOTICE and document['looks'] == rows
    assert [row['name'] for row in rows] == list(SIX)
    assert [row['exposure_comp_thirds'] for row in rows] == [2, 0, 1, 1, 1, 0]
    assert [row['licence'] for row in rows] == [DEHANCER_LICENCE, BUNDLED_LICENCE] + [DEHANCER_LICENCE] * 3 + [DXO_LICENCE]
    for slot, row in enumerate(rows, 1):
        assert row['file'] == 'slot%d.a7look' % slot
        assert (pack / row['file']).read_bytes() == (source / by_id[row['library_id']]['file']).read_bytes()
        assert row['sha256'] == sha(pack / row['file'])
    assert presets.read(pack / 'pack.json', presets.PERSONAL).names == tuple(SIX)
    staged = tmp_path / 'personal-six-v1.partial'  # checked as One-click will read them, before the swap
    assert [call.args for call in checked_slots.call_args_list] == [
        (staged / ('slot%d.a7look' % slot), name) for slot, name in enumerate(SIX, 1)]


# Refusals leave the previous assets in place --------------------------------------------------------

def refused(tmp_path, source, match):
    with pytest.raises(ValueError, match=match):
        prepare(tmp_path, source)
    for target, descriptor in (('film-looks-personal-v1', 'catalog.json'), ('personal-six-v1', 'pack.json')):
        assert (tmp_path / target / descriptor).read_text(encoding='utf-8') == 'previous'


@pytest.fixture
def previous(tmp_path):
    """Earlier personal assets, which a refused preparation must leave as they are."""
    for target, descriptor in (('film-looks-personal-v1', 'catalog.json'), ('personal-six-v1', 'pack.json')):
        (tmp_path / target).mkdir()
        (tmp_path / target / descriptor).write_text('previous', encoding='utf-8')


def with_change(index, **change):
    looks = [dict(row) for row in LOOKS]
    looks[index].update(change)
    return looks


def test_a_look_that_does_not_match_its_checksum_is_refused(tmp_path, previous, checked_slots):
    refused(tmp_path, library(tmp_path, with_change(2, sha256='0' * 64)), 'dh-velvia50.a7look does not match')


def test_a_library_not_marked_personal_use_only_is_refused(tmp_path, previous, checked_slots):
    refused(tmp_path, library(tmp_path, personal_use_only=False), 'personal_use_only')


@pytest.mark.parametrize('index, change, match', [
    (3, dict(stock='Gold 200'), "No film kind for the stock 'Gold 200'"),
    (3, dict(source='filmbox'), "Unknown source 'filmbox'"),
    (3, dict(camera_name='Portra 400'), "is named 'Portra 400 \\(Dehancer\\)', not 'Portra 400'"),
    (3, dict(id='../escape'), 'Unsafe look id'),
    (3, dict(file='../outside.a7look'), 'outside the library'),
    (3, dict(exposure_comp_thirds=-1), 'exposure'),
    (3, dict(default_slot=None), 'Custom 1–6 one look each'),
    (1, dict(default_slot=2), 'Custom 1–6 one look each'),
    (3, dict(default_slot=7), 'Custom 1–6 one look each'),
    (3, dict(default_slot='1'), 'Custom 1–6 one look each'),
    (3, dict(default_slot=True), 'Custom 1–6 one look each'),
], ids=['unknown-stock', 'unknown-source', 'renamed', 'unsafe-id', 'file-outside', 'negative-exposure',
        'five-slots', 'two-in-one-slot', 'slot-seven', 'slot-as-text', 'slot-as-bool'])
def test_an_inconsistent_manifest_is_refused(tmp_path, previous, checked_slots, index, change, match):
    looks = with_change(index, **change)
    if change.get('camera_name'):  # the file keeps its own name; only the manifest changes
        source = library(tmp_path, LOOKS)
        document = json.loads((source / 'manifest.json').read_text(encoding='utf-8'))
        document['looks'][index]['camera_name'] = change['camera_name']
        (source / 'manifest.json').write_text(json.dumps(document), encoding='utf-8')
    elif change.get('file'):
        source = library(tmp_path, LOOKS)
        document = json.loads((source / 'manifest.json').read_text(encoding='utf-8'))
        document['looks'][index]['file'] = change['file']
        (source / 'manifest.json').write_text(json.dumps(document), encoding='utf-8')
    else:
        source = library(tmp_path, looks)
    refused(tmp_path, source, match)


def test_an_unknown_conversion_method_is_refused(tmp_path, previous, checked_slots):
    source = library(tmp_path)
    path = source / 'looks/dh-velvia50.a7look'
    document = json.loads(path.read_text(encoding='utf-8'))
    document['method'] = 'mystery'
    path.write_text(json.dumps(document), encoding='utf-8')
    manifest = json.loads((source / 'manifest.json').read_text(encoding='utf-8'))
    manifest['looks'][2]['sha256'] = sha(path)
    (source / 'manifest.json').write_text(json.dumps(manifest), encoding='utf-8')
    refused(tmp_path, source, "unknown conversion method 'mystery'")


def test_a_pack_slot_the_app_would_refuse_leaves_both_targets_as_they_were(tmp_path, previous, checked_slots):
    checked_slots.side_effect = ValueError('内置外观名称／照片阶段不符：slot4.a7look')
    refused(tmp_path, library(tmp_path), '内置外观名称')


@pytest.mark.parametrize('target', ['film-looks-personal-v1', 'personal-six-v1'])
def test_a_folder_that_is_not_a_personal_asset_is_never_replaced(tmp_path, checked_slots, target):
    (tmp_path / target).mkdir()
    (tmp_path / target / 'keep.txt').write_text('mine')
    with pytest.raises(RuntimeError, match='Refusing to replace'):
        prepare(tmp_path, library(tmp_path))
    assert [path.name for path in (tmp_path / target).iterdir()] == ['keep.txt']
    other = ({'film-looks-personal-v1', 'personal-six-v1'} - {target}).pop()
    assert not (tmp_path / other).exists()  # checked before either target changes
    assert sorted(path.name for path in tmp_path.iterdir()) == sorted(['personal-library', target])


@pytest.mark.parametrize('why, kept', [
    ('Skin first. Fit: MAE 1.26 / P95 4.03, within the median bundled look (2.39 / 8.02).', 'Skin first.'),
    ('Fit: MAE 2.07 / P95 7.13, within the median bundled look (2.39 / 8.02).', ''),
    ('Kept for its beauty. The accurate one fits better.', 'Kept for its beauty. The accurate one fits better.'),
])
def test_the_rationale_drops_its_fit_sentence_which_the_library_shows_itself(why, kept):
    assert personal.rationale(why) == kept
