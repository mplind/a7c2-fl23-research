"""The One-click page and its write confirmation name the six looks of the pack One-click installs: the owner's
personal pack when its pack.json is present, else the public pack exactly as before. No camera: no job
starts, and every confirmation is answered Cancel."""
import json
import os
from pathlib import Path
from unittest.mock import patch

import pytest
from PySide6 import QtWidgets as W

from desktopapp import jobs, presets
from desktopapp.en import STRINGS
from desktopapp.en_engine import ENGINE
from desktopapp.window import Window
from guihelpers import shown_texts

ROOT = Path(__file__).resolve().parents[2]
PUBLIC = ROOT / 'desktop-assets/presets' / presets.PACK
PUBLIC_AVAILABLE = (PUBLIC / 'slot6.a7look').is_file()
REAL_PERSONAL = ROOT / 'desktop-assets/presets' / presets.PERSONAL
# The owner's six, Custom 1–6, as he chose them on 29 Oct 2026.
OWNER_SIX = ('Portra 400 (Dehancer)', 'Classic Chrome', 'Kodachrome 64 (Dehancer)', 'Velvia 50 (Dehancer)',
             'CineStill 800T (Dehancer)', 'Portra 160 NC (DxO)')
NAMES = ('Look One', 'Look Two', 'Look Three', 'Look Four', 'Look Five', 'Look Six')
TARGET = 'The ticked features, with these looks: '


@pytest.fixture
def assets(tmp_path, monkeypatch):
    """presets on a checkout at tmp_path whose public pack is the real one (when this checkout has it) and
    which has no personal pack until a test writes one."""
    folder = tmp_path / 'desktop-assets/presets'
    folder.mkdir(parents=True)
    if PUBLIC.is_dir():
        os.symlink(PUBLIC, folder / presets.PACK)
    monkeypatch.setattr(presets, 'ROOT', tmp_path)
    return folder


def personal_pack(assets, names=NAMES, thirds=(2, 0, 1, 1, 1, 0), files=False):
    """A personal pack of `names`; with `files`, its slot files are the public pack's, renamed to match."""
    folder = assets / presets.PERSONAL
    folder.mkdir()
    rows = [dict(slot=slot, name=name, file='slot%d.a7look' % slot, exposure_comp_thirds=dark)
            for slot, (name, dark) in enumerate(zip(names, thirds), 1)]
    (folder / 'pack.json').write_text(json.dumps(dict(pack=presets.PERSONAL, looks=rows)), encoding='utf-8')
    if files:
        for slot in range(1, 7):
            os.symlink(PUBLIC / ('slot%d.a7look' % slot), folder / ('slot%d.a7look' % slot))
    return folder


def home_texts(ui):
    return shown_texts(ui.pages.widget(0))


# Without the personal pack: exactly as before -------------------------------------------------------

def test_without_the_personal_pack_the_one_click_page_is_as_before(window, assets):
    ui = window('en')
    assert ui.setup_preset_summary.text() == STRINGS[presets.SUMMARY]
    assert ui.setup_args()['options']['preset_pack'] == presets.PACK
    assert Window.write_target('setup_all', ui.setup_args(), False) == TARGET + STRINGS[presets.SUMMARY]
    chinese = window('zh_CN')
    assert chinese.setup_preset_summary.text() == presets.SUMMARY
    assert Window.write_target('setup_all', chinese.setup_args(), False) == '首页勾选的功能；替换自订 1–6：' + presets.SUMMARY


# With the personal pack ----------------------------------------------------------------------------

LINE = 'Look One, Look Two, Look Three, Look Four, Look Five, Look Six. They replace what is in Custom 1–6 now, ' \
       'settings included. The camera’s own Creative Looks stay.'
EXPOSURE = ('Look One renders about ⅔ stop dark; add +⅔ EV.\n'
            'Look Three, Look Four, Look Five render about ⅓ stop dark; add +⅓ EV.')


def test_the_one_click_page_names_the_personal_six_and_the_exposure_they_need(window, assets):
    personal_pack(assets)
    ui = window('en')
    assert ui.setup_preset_summary.text() == LINE + '\n' + EXPOSURE
    assert ui.setup_args()['options']['preset_pack'] == presets.PERSONAL
    texts = '\n'.join(home_texts(ui))
    assert [name for name in presets.NAMES if name in texts] == []  # nothing names the public six
    chinese = window('zh_CN')
    assert chinese.setup_preset_summary.text() == (
        'Look One、Look Two、Look Three、Look Four、Look Five、Look Six（依次装入自订 1–6）\n'
        'Look One 画面约暗 ⅔ 档，曝光补偿 +⅔ EV。\n'
        'Look Three、Look Four、Look Five 画面均约暗 ⅓ 档，曝光补偿均 +⅓ EV。')


def test_a_pack_without_dark_looks_has_no_exposure_line(window, assets):
    personal_pack(assets, thirds=(0,) * 6)
    assert window('en').setup_preset_summary.text() == LINE


def test_the_write_confirmation_names_the_six_of_the_pack_the_job_installs(window, assets):
    personal_pack(assets)
    ui = window('en')
    assert Window.write_target('setup_all', ui.setup_args(), False) == TARGET + LINE  # no exposure advice here
    public = dict(options=dict(preset_pack=presets.PACK, looks=[]))
    assert Window.write_target('setup_all', public, False) == TARGET + STRINGS[presets.SUMMARY]
    own = dict(options=dict(preset_pack=None, looks=[dict(slot=2, path='mine.a7look')]))
    assert Window.write_target('setup_all', own, False) == STRINGS['首页勾选的功能及所选 A7Look 槽位']


def test_the_page_refreshes_its_line_from_the_active_pack(window, assets):
    ui = window('en')
    personal_pack(assets)
    ui.refresh_setup_controls()
    assert ui.setup_preset_summary.text() == LINE + '\n' + EXPOSURE


def test_an_unreadable_personal_pack_says_why_and_stops_one_click_before_any_prompt(window, assets):
    folder = assets / presets.PERSONAL
    folder.mkdir()
    (folder / 'pack.json').write_text('{not json', encoding='utf-8')
    ui = window('en')
    expected = ENGINE['内置六款外观包描述无效，请使用完整工具包；尚未连接相机：%s'] % (folder / 'pack.json')
    assert ui.setup_preset_summary.text() == expected
    with patch.object(ui, 'drivers_first', side_effect=AssertionError('driver prompt shown')), \
            patch('desktopapp.window.ask') as asked, patch.object(W.QMessageBox, 'warning') as warned, \
            patch.object(jobs, 'new_job') as new:
        ui.launch('setup_all', ui.setup_args())
    asked.assert_not_called(); new.assert_not_called()
    assert warned.call_args.args[2] == expected


def test_a_saved_job_names_its_own_looks_when_its_pack_is_gone(assets):
    saved = [dict(slot=slot, name=name, path='inputs/slot%d.a7look' % slot) for slot, name in enumerate(NAMES, 1)]
    arguments = dict(options=dict(preset_pack=presets.PERSONAL, looks=saved))
    with patch('desktopapp.i18n._language', 'en'):
        assert Window.write_target('setup_all', arguments, False) == TARGET + ', '.join(NAMES)


def test_a_pending_job_of_the_personal_pack_keeps_the_box_ticked(window, assets, tmp_path):
    from desktopapp.paths import data_root, write_json
    root = tmp_path / 'pending'; root.mkdir()
    saved = [dict(slot=slot, name=name, path='inputs/slot%d.a7look' % slot) for slot, name in enumerate(NAMES, 1)]
    options = dict(fl23=True, sound=False, vertical=False, preset_pack=presets.PERSONAL, looks=saved)
    (root / 'setup.private.json').write_text(json.dumps(dict(phase='WAIT_RELOAD', options=options)))
    ui = window('en')
    write_json(data_root() / 'desktop.json', dict(ui.settings, setup_work=str(root)))
    pending = window()
    assert pending.setup_presets.isChecked() and not pending.setup_presets.isEnabled()
    assert pending.setup_args()['options'] == options


@pytest.mark.skipif(not PUBLIC_AVAILABLE, reason='the built-in six are a distribution asset')
def test_one_click_checks_and_confirms_the_personal_six(window, assets):
    personal_pack(assets, names=presets.NAMES, files=True)  # real slot files, their own names
    ui = window('en')
    asked = []
    with patch.object(ui, 'drivers_first', return_value=True), \
            patch('desktopapp.window.ask', side_effect=lambda parent, title, text, verb, **k: asked.append(text)), \
            patch.object(jobs, 'new_job') as new:
        ui.setup_button.click()
    new.assert_not_called()
    assert TARGET + ', '.join(presets.NAMES) + '. They replace' in asked[-1]


# The owner's own pack, where this checkout has it ------------------------------------------------------

@pytest.mark.skipif(not (REAL_PERSONAL / 'pack.json').is_file(), reason="The owner's personal pack is a personal asset")
def test_the_one_click_page_and_confirmation_name_prices_six(window):
    ui = window('en')
    line = ', '.join(OWNER_SIX) + '. They replace what is in Custom 1–6 now, settings included. ' \
                                  'The camera’s own Creative Looks stay.'
    assert ui.setup_preset_summary.text() == line + '\n' + (
        'Portra 400 (Dehancer) renders about ⅔ stop dark; add +⅔ EV.\n'
        'Kodachrome 64 (Dehancer), Velvia 50 (Dehancer), CineStill 800T (Dehancer) render about ⅓ stop dark; '
        'add +⅓ EV.')
    asked = []
    with patch.object(ui, 'drivers_first', return_value=True), \
            patch('desktopapp.window.ask', side_effect=lambda parent, title, text, verb, **k: asked.append(text)), \
            patch.object(jobs, 'new_job') as new:
        ui.setup_button.click()
    new.assert_not_called()
    assert TARGET + line in asked[-1]
    assert [name for name in presets.NAMES if name != 'Classic Chrome' and name in asked[-1]] == []
