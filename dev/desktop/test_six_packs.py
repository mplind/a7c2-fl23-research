"""The six-look packs One-click installs: the public pack from its constants, the owner's personal pack from
its pack.json, which of the two is active, and the lines that name a pack's six and the exposure its
dark looks need. No camera, no USB."""
import json
import os
from pathlib import Path

import pytest

from desktopapp import presets
from desktopapp.en import STRINGS

ROOT = Path(__file__).resolve().parents[2]
PUBLIC = ROOT / 'desktop-assets/presets' / presets.PACK
PUBLIC_AVAILABLE = (PUBLIC / 'slot6.a7look').is_file()
NAMES = ('Look One', 'Look Two', 'Look Three', 'Look Four', 'Look Five', 'Look Six')
REPLACES = ' They replace what is in Custom 1–6 now, settings included. The camera’s own Creative Looks stay.'


def rows(names=NAMES, thirds=(0,) * 6):
    return [dict(slot=slot, name=name, file='slot%d.a7look' % slot, exposure_comp_thirds=dark)
            for slot, (name, dark) in enumerate(zip(names, thirds), 1)]


def write_pack(folder, document=None, **change):
    """A personal pack.json in `folder`: six rows of NAMES unless `document` or `change` says otherwise."""
    if document is None:
        document = dict(dict(pack=presets.PERSONAL, personal_use_only=True, notice='Personal use only.', looks=rows()),
                        **change)
    folder.mkdir(parents=True, exist_ok=True)
    (folder / 'pack.json').write_text(document if isinstance(document, str) else json.dumps(document),
                                      encoding='utf-8')
    return folder


@pytest.fixture
def root(tmp_path, monkeypatch):
    """presets on an empty checkout at tmp_path: no pack files at all."""
    monkeypatch.setattr(presets, 'ROOT', tmp_path)
    return tmp_path


def personal(root):
    return root / 'desktop-assets/presets' / presets.PERSONAL


# Which pack is active ------------------------------------------------------------------------------

def test_without_the_personal_pack_the_public_pack_is_active_as_before(root):
    assert presets.active() == presets.PACK
    pack = presets.load(presets.PACK)
    assert (pack.id, pack.names, pack.dark) == (presets.PACK, presets.NAMES, ())
    assert presets.catalog(presets.PACK) == [
        dict(slot=slot, name=name, path=str(root / 'desktop-assets/presets/default-six-v1' / ('slot%d.a7look' % slot)))
        for slot, name in enumerate(presets.NAMES, 1)]


def test_the_personal_pack_is_active_once_its_pack_json_is_present(root):
    personal(root).mkdir(parents=True)  # a folder without its pack.json is not a pack
    assert presets.active() == presets.PACK
    write_pack(personal(root), looks=rows(thirds=(2, 0, 1, 1, 1, 0)))
    assert presets.active() == presets.PERSONAL
    pack = presets.load(presets.PERSONAL)
    assert pack.names == NAMES
    assert pack.dark == (('Look One', 2), ('Look Three', 1), ('Look Four', 1), ('Look Five', 1))
    assert [row['path'] for row in presets.catalog(presets.PERSONAL)] == [
        str(personal(root) / ('slot%d.a7look' % slot)) for slot in range(1, 7)]


def test_an_unknown_pack_is_refused(root):
    with pytest.raises(ValueError, match='Unknown built-in look pack: other-six'):
        presets.load('other-six')


def test_a_personal_pack_without_its_pack_json_is_refused_before_the_camera(root):
    with pytest.raises(ValueError, match='内置六款外观文件缺失.*尚未连接相机') as refused:
        presets.load(presets.PERSONAL)
    assert str(personal(root) / 'pack.json') in str(refused.value)


def five():
    return rows()[:5]


def reordered():
    found = rows()
    found[0], found[1] = found[1], found[0]
    return found


def renamed_file():
    found = rows()
    found[2]['file'] = '../slot3.a7look'
    return found


def change_row(key, value):
    found = rows()
    found[3][key] = value
    return found


@pytest.mark.parametrize('document', [
    '{not json',
    '[]',
    dict(pack='default-six-v1', looks=rows()),
    dict(pack=presets.PERSONAL),
    dict(pack=presets.PERSONAL, looks='six'),
    dict(pack=presets.PERSONAL, looks=five()),
    dict(pack=presets.PERSONAL, looks=rows() + rows()[:1]),
    dict(pack=presets.PERSONAL, looks=reordered()),
    dict(pack=presets.PERSONAL, looks=renamed_file()),
    dict(pack=presets.PERSONAL, looks=rows()[:5] + ['slot6']),
    dict(pack=presets.PERSONAL, looks=change_row('name', '  ')),
    dict(pack=presets.PERSONAL, looks=change_row('name', 7)),
    dict(pack=presets.PERSONAL, looks=change_row('exposure_comp_thirds', -1)),
    dict(pack=presets.PERSONAL, looks=change_row('exposure_comp_thirds', 1.0)),
    dict(pack=presets.PERSONAL, looks=change_row('exposure_comp_thirds', True)),
    dict(pack=presets.PERSONAL, looks=change_row('exposure_comp_thirds', None)),
], ids=['malformed', 'not-an-object', 'other-pack', 'no-looks', 'looks-not-a-list', 'five', 'seven', 'reordered',
        'file-outside', 'row-not-an-object', 'blank-name', 'name-not-text', 'negative-exposure', 'float-exposure',
        'bool-exposure', 'no-exposure'])
def test_an_invalid_personal_pack_json_is_refused_before_the_camera(root, document):
    write_pack(personal(root), document)
    with pytest.raises(ValueError, match='内置六款外观包描述无效.*尚未连接相机') as refused:
        presets.load(presets.PERSONAL)
    assert str(personal(root) / 'pack.json') in str(refused.value)
    with pytest.raises(ValueError, match='内置六款外观包描述无效'):
        presets.resolve(dict(preset_pack=presets.PERSONAL))


def test_the_engine_messages_have_english_that_names_the_next_step():
    from desktopapp.en_engine import ENGINE, NEXT_STEP
    for source in ('内置六款外观文件缺失，请使用完整工具包；尚未连接相机：%s',
                   '内置六款外观包描述无效，请使用完整工具包；尚未连接相机：%s'):
        assert 'Reinstall the complete app' in ENGINE[source] and source in NEXT_STEP


# A pack.json pack resolves like the public pack ---------------------------------------------------

@pytest.mark.skipif(not PUBLIC_AVAILABLE, reason='the built-in six are a distribution asset')
def test_a_pack_json_pack_resolves_its_six_files_in_its_own_order(root):
    folder = personal(root)
    order = (6, 5, 4, 3, 2, 1)  # the public pack's files, reversed, stand in for six personal looks
    names = tuple(presets.NAMES[number - 1] for number in order)
    write_pack(folder, looks=rows(names))
    for slot, number in enumerate(order, 1):
        os.symlink(PUBLIC / ('slot%d.a7look' % number), folder / ('slot%d.a7look' % slot))
    resolved = presets.resolve(dict(preset_pack=presets.PERSONAL, fl23=True))
    assert resolved['looks'] == [dict(slot=slot, name=name, path=str(folder / ('slot%d.a7look' % slot)))
                                 for slot, name in enumerate(names, 1)]
    assert resolved['fl23'] is True
    write_pack(folder, looks=rows(names[:5] + ('Not its name',)))
    with pytest.raises(ValueError, match='内置外观名称／照片阶段不符'):
        presets.resolve(dict(preset_pack=presets.PERSONAL))


def test_a_missing_slot_file_of_the_personal_pack_stops_before_the_camera(root):
    write_pack(personal(root))
    with pytest.raises(ValueError, match='内置六款外观文件缺失.*尚未连接相机') as refused:
        presets.resolve(dict(preset_pack=presets.PERSONAL))
    assert str(personal(root) / 'slot1.a7look') in str(refused.value)


# The lines that name the six and the exposure they need --------------------------------------------

def test_the_public_packs_line_is_exactly_as_before(root):
    pack = presets.load(presets.PACK)
    assert presets.summary(pack, 'zh_CN') == '1 NC · 2 CC · 3 NN · 4 Astia · 5 GR 正片 · 6 GR 负片'
    assert presets.summary(pack, 'en') == ('Classic Neg., Classic Chrome, Nostalgic Neg., Astia, GR Positive and '
                                           'GR Negative.' + REPLACES)
    assert presets.exposure_note(pack.dark, 'en') == ''


def test_a_pack_json_packs_line_names_its_six_in_slot_order(root):
    write_pack(personal(root))
    pack = presets.load(presets.PERSONAL)
    assert presets.summary(pack, 'en') == 'Look One, Look Two, Look Three, Look Four, Look Five, Look Six.' + REPLACES
    assert presets.summary(pack, 'zh_CN') == 'Look One、Look Two、Look Three、Look Four、Look Five、Look Six（依次装入自订 1–6）'
    assert STRINGS[presets.IN_ORDER] == '%s.' + REPLACES


@pytest.mark.parametrize('thirds, written', [(1, '⅓'), (2, '⅔'), (3, '1'), (4, '1⅓'), (5, '1⅔'), (6, '2')])
def test_stops_are_written_in_thirds(thirds, written):
    assert presets.stops(thirds) == written


def test_the_exposure_note_groups_dark_looks_by_amount_in_slot_order():
    dark = (('Look One', 2), ('Look Three', 1), ('Look Four', 1), ('Look Five', 1))
    assert presets.exposure_note(dark, 'en') == (
        'Look One renders about ⅔ stop dark; add +⅔ EV.\n'
        'Look Three, Look Four, Look Five render about ⅓ stop dark; add +⅓ EV.')
    assert presets.exposure_note(dark, 'zh_CN') == (
        'Look One 画面约暗 ⅔ 档，曝光补偿 +⅔ EV。\n'
        'Look Three、Look Four、Look Five 画面均约暗 ⅓ 档，曝光补偿均 +⅓ EV。')
    assert presets.exposure_note((('Look Two', 3),), 'en') == 'Look Two renders about 1 stop dark; add +1 EV.'
    assert presets.exposure_note((), 'en') == ''


def test_a_last_name_that_ends_in_a_full_stop_ends_the_sentence_once(root):
    write_pack(personal(root), looks=rows(NAMES[:5] + ('Classic Neg.',)))
    pack = presets.load(presets.PERSONAL)
    assert presets.summary(pack, 'en') == 'Look One, Look Two, Look Three, Look Four, Look Five, Classic Neg.' + REPLACES
    assert presets.summary(pack, 'zh_CN').endswith('Classic Neg.（依次装入自订 1–6）')


def test_a_look_that_does_not_render_dark_gets_no_exposure_line():
    assert presets.exposure_note((('Look Two', 0),), 'en') == ''
    assert presets.exposure_note((('Look One', 0), ('Look Two', 1)), 'en') == 'Look Two renders about ⅓ stop dark; add +⅓ EV.'
