"""Shutter sound page: the bundled presets fill the clip fields; no camera access."""
import json

import pytest
from PySide6 import QtWidgets as W

from desktopapp import shuttersounds
from guihelpers import HAN_OR_PUNCTUATION
from test_shuttersounds import entry, write_catalog, write_wav

NAMES = ['Leica M3', 'Hasselblad 500C', 'Pentax 6x7']


@pytest.fixture
def library(tmp_path, monkeypatch):
    folder = tmp_path / 'shutter-sounds-v1'
    entries = [entry(id=name.lower().replace(' ', '-'), name=name, file=name.lower().replace(' ', '-') + '.wav')
               for name in NAMES]
    write_catalog(folder, entries, wav=False)
    for index, item in enumerate(entries):
        write_wav(folder / item['file'], seconds=0.4 + index / 10)
    monkeypatch.setattr(shuttersounds, 'location', lambda: folder)
    return folder


def preset(ui):
    return ui.findChild(W.QComboBox, 'sound_preset')


def test_the_page_offers_your_own_file_then_the_presets_most_loved_first(window, library):
    ui = window('en')
    menu = preset(ui)
    assert [menu.itemText(i) for i in range(menu.count())] == ['Your own file'] + NAMES
    assert menu.currentIndex() == 0
    assert 'ranked' in ui.sound_credit.text() and not HAN_OR_PUNCTUATION.search(ui.sound_credit.text())


def test_choosing_a_preset_fills_the_file_start_and_length_and_shows_its_credit(window, library):
    ui = window('en')
    ui.sound_start.setValue(12.5)
    preset(ui).setCurrentIndex(2)
    assert ui.fields['sound_source'].text() == str(library / 'hasselblad-500c.wav')
    assert (ui.sound_start.value(), ui.sound_duration.value()) == (0, 0.5)
    credit = ui.sound_credit.text()
    assert '"Leica M3 Shutter sound" by petrich0r' in credit and 'CC BY 4.0' in credit
    assert 'href="https://freesound.org/s/683763/"' in credit and ui.sound_credit.openExternalLinks()
    assert '--' not in credit  # the formal attribution line lives in CREDITS.txt


def test_converting_a_preset_sends_the_bundled_clip_to_the_worker(window, library):
    ui = window('en')
    preset(ui).setCurrentIndex(1)
    ui.findChild(W.QPushButton, 'action_sound_import').click()
    request = json.loads((ui.current_job / 'request.private.json').read_text())
    assert request['action'] == 'sound_import'
    assert (request['arguments']['source'], request['arguments']['start'], request['arguments']['duration']) == (
        str(library / 'leica-m3.wav'), 0, 0.4)


def test_choosing_another_file_switches_back_to_your_own_file(window, library):
    ui = window('en')
    preset(ui).setCurrentIndex(3)
    ui.fields['sound_source'].setText('/Users/me/my shutter.wav')
    assert preset(ui).currentIndex() == 0
    assert 'ranked' in ui.sound_credit.text()
    assert ui.fields['sound_source'].text() == '/Users/me/my shutter.wav'  # the user's file is left alone


def test_a_saved_preset_is_selected_again_on_the_next_launch(window, library):
    from desktopapp.paths import load_settings, save_settings
    window('en')
    save_settings(dict(load_settings(), sound_source=str(library / 'pentax-6x7.wav')))
    reopened = window()
    assert preset(reopened).currentIndex() == 3
    assert 'freesound.org' in reopened.sound_credit.text()


def test_without_a_library_the_page_has_no_preset_menu(window, tmp_path, monkeypatch):
    monkeypatch.setattr(shuttersounds, 'location', lambda: tmp_path / 'absent')
    ui = window('en')
    assert preset(ui) is None
    assert ui.fields['sound_source'] is not None


def test_a_broken_library_is_reported_in_the_log_and_the_page_still_opens(window, tmp_path, monkeypatch):
    folder = tmp_path / 'broken'
    folder.mkdir()
    (folder / 'catalog.json').write_text('{"schema": "other/1"}')
    monkeypatch.setattr(shuttersounds, 'location', lambda: folder)
    ui = window('en')
    assert preset(ui) is None
    assert 'shutter sound' in ui.log.toPlainText().lower()


def test_the_presets_read_in_chinese_too(window, library):
    ui = window('zh_CN')
    assert preset(ui).itemText(0) == '自己的文件'
    assert '排序' in ui.sound_credit.text()


def test_going_back_to_your_own_file_clears_only_a_bundled_clip(window, library):
    ui = window('en')
    preset(ui).setCurrentIndex(1)
    preset(ui).setCurrentIndex(0)
    assert ui.fields['sound_source'].text() == ''  # the menu and the field agree
    ui.fields['sound_source'].setText('/Users/me/my shutter.wav')
    preset(ui).setCurrentIndex(0)
    assert ui.fields['sound_source'].text() == '/Users/me/my shutter.wav'


def test_a_bundled_clip_is_recognised_however_its_path_is_written(window, library):
    ui = window('en')
    ui.fields['sound_source'].setText(str(library / 'leica-m3.wav').replace('/', '//'))
    assert preset(ui).currentIndex() == 1


def test_a_preset_saved_from_an_older_copy_of_the_app_points_at_this_copy(window, library):
    # Picked while running from the disk image, then the app moved to Applications.
    from desktopapp.paths import load_settings, save_settings
    window('en')
    save_settings(dict(load_settings(), sound_source='/Volumes/A7C2Tools/A7C2Tools.app/Contents/Resources/'
                                                      'desktop-assets/shutter-sounds-v1/pentax-6x7.wav'))
    ui = window()
    assert preset(ui).currentIndex() == 3
    assert ui.fields['sound_source'].text() == str(library / 'pentax-6x7.wav')


def test_a_credit_shows_only_the_source_fields(window, library):
    ui = window('en')
    sound = dict(preset(ui).itemData(1))
    sound['source'] = dict(sound['source'], extra=7)  # catalog fields beyond the credit are ignored
    preset(ui).setItemData(1, sound)
    preset(ui).setCurrentIndex(1)
    assert 'petrich0r' in ui.sound_credit.text()
