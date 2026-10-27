"""Film look library, fit display, offline preview and fit warning in the GUI; no camera access."""
import json
import os
from pathlib import Path
import time
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import numpy as np
import pytest
from PIL import Image
from PySide6 import QtWidgets as W
from desktopapp import i18n, jobs, looklibrary
from desktopapp.lookeditor import LookEditor
from desktopapp.lookviews import FilmLibraryDialog, PreviewDialog, fit_text
from desktopapp.window import Window
from looksamples import look_file

HAN = __import__('re').compile('[㐀-鿿（），：；、。“”]')


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.setenv('A7C2_DESKTOP_DATA', str(tmp_path / 'data'))
    return W.QApplication.instance() or W.QApplication([])


@pytest.fixture
def english():
    i18n.configure('en')
    yield
    i18n.configure('zh_CN')


@pytest.fixture
def window(app):
    windows = []
    def create():
        result = Window(); result.timer.stop(); windows.append(result)
        return result
    yield create
    for result in windows:
        result.process = None; result.close()


def write_row(editor, path, slot=1):
    row = editor.add_row(slot)
    row.action.setCurrentIndex(1)
    row.set_file(str(path))
    return row


@pytest.mark.parametrize('mae,p95,expected', [
    (2.0, 7.0, 'Fit: good (MAE 2.0 · P95 7.0)'),
    (4.0, 12.0, 'Fit: fair (MAE 4.0 · P95 12.0)'),
])
def test_a_write_row_shows_the_measured_fit_of_its_file(app, english, tmp_path, mae, p95, expected):
    editor = LookEditor()
    row = write_row(editor, look_file(tmp_path / 'look.a7look', mae=mae, p95=p95))
    assert row.fit.text() == expected and not row.fit.property('warning')
    assert not row.fit.isHidden()


def test_a_poor_unknown_or_unreadable_fit_is_shown_as_a_warning(app, english, tmp_path):
    editor = LookEditor()
    poor = write_row(editor, look_file(tmp_path / 'poor.a7look', mae=6.0, p95=20.0), 1)
    unknown = write_row(editor, look_file(tmp_path / 'unknown.a7look'), 2)
    broken = write_row(editor, tmp_path / 'missing.a7look', 3)
    assert poor.fit.text().startswith('Fit: poor (MAE 6.0 · P95 20.0)') and 'differ' in poor.fit.text()
    assert unknown.fit.text() == 'Fit: unknown (the file has no held-out validation data)'
    assert broken.fit.text().startswith('Cannot read this A7Look: ')
    assert all(row.fit.property('warning') for row in (poor, unknown, broken))


def test_fit_and_preview_wait_for_a_file(app, tmp_path):
    editor = LookEditor()
    row = editor.add_row(1); row.action.setCurrentIndex(1)
    assert row.fit.isHidden() and not row.preview.isEnabled()
    row.set_file(str(look_file(tmp_path / 'look.a7look', mae=2.0, p95=7.0)))
    assert not row.fit.isHidden() and row.preview.isEnabled()


def test_preview_and_library_buttons_ask_the_window(app, tmp_path):
    editor = LookEditor()
    path = str(look_file(tmp_path / 'look.a7look', mae=2.0, p95=7.0))
    previews, libraries = [], []
    editor.preview_requested.connect(previews.append)
    editor.library_requested.connect(lambda: libraries.append(True))
    write_row(editor, path).preview.click()
    editor.library.click()
    assert previews == [path] and libraries == [True]


def test_fit_text_lists_every_rating_in_english(english):
    for rating in ('good', 'fair', 'poor'):
        assert not HAN.search(fit_text(dict(rating=rating, mae=1.0, p95=2.0)))
    assert not HAN.search(fit_text(dict(rating='unknown', mae=None, p95=None)))


def library(tmp_path):
    folder = tmp_path / 'library'; folder.mkdir()
    entries = []
    for slug, name, kind, mae, notes in (('portra400', 'Portra 400', 'negative', 3.07, ''),
                                        ('velvia100', 'Velvia 100', 'slide', 3.48, 'Slight cyan cast in deep shadows.')):
        look_file(folder / (slug + '.a7look'), mae=mae, p95=9.0, name=name)
        entries.append({'id': slug, 'name': name, 'kind': kind, 'file': slug + '.a7look',
                        'source': {'project': 'spektrafilm', 'author': 'Andrea Volpato',
                                   'url': 'https://github.com/andreavolpato/spektrafilm', 'licence': 'CC BY-SA 4.0'},
                        'modification': 'Baked to a 33^3 cube', 'shareable': True, 'notes': notes})
    (folder / 'catalog.json').write_text(json.dumps({'schema': looklibrary.SCHEMA, 'looks': entries}))
    return looklibrary.catalog(folder)


def test_library_lists_looks_and_shows_source_licence_and_notes(app, english, tmp_path):
    dialog = FilmLibraryDialog(library(tmp_path))
    assert [dialog.list.item(i).text() for i in range(dialog.list.count())] == [
        'Portra 400 · Colour negative · Fit: fair', 'Velvia 100 · Slide · Fit: fair']
    dialog.list.setCurrentRow(1)
    details = dialog.details.toPlainText()
    for text in ('Velvia 100', 'spektrafilm', 'Andrea Volpato', 'CC BY-SA 4.0', 'Baked to a 33^3 cube',
                 'Slight cyan cast', 'MAE 3.5'):
        assert text in details
    assert 'https://github.com/andreavolpato/spektrafilm' in dialog.details.toHtml()
    assert not any(HAN.search(text) for text in [dialog.windowTitle(), details] +
                   [b.text() for b in dialog.findChildren(W.QAbstractButton)])


def test_library_add_and_preview_send_the_selected_look(app, tmp_path):
    looks = library(tmp_path)
    dialog = FilmLibraryDialog(looks)
    added, previews = [], []
    dialog.add_requested.connect(lambda look, slot: added.append((look['id'], slot)))
    dialog.preview_requested.connect(previews.append)
    dialog.list.setCurrentRow(1); dialog.slot.setCurrentIndex(4)
    dialog.add.click(); dialog.preview.click()
    assert added == [('velvia100', 5)] and previews == [str(looks[1]['path'])]


def test_window_adds_a_library_look_as_a_write_row_or_updates_that_slot(window, tmp_path):
    ui = window()
    first, second = library(tmp_path)
    assert ui.add_library_look(first, 2)
    assert ui.look_editor.values() == [dict(slot=2, action='write', path=str(first['path']), name='')]
    ui.look_editor.add_row(4)
    assert ui.add_library_look(second, 4)
    assert ui.look_editor.values()[1] == dict(slot=4, action='write', path=str(second['path']), name='')
    assert len(ui.look_editor.rows) == 2


def test_window_does_not_add_to_a_locked_list(window, tmp_path):
    ui = window()
    ui.look_editor.setEnabled(False)
    with patch.object(W.QMessageBox, 'information') as told:
        assert not ui.add_library_look(library(tmp_path)[0], 1)
    told.assert_called_once()
    assert ui.look_editor.values() == []


def test_a_poor_fit_asks_before_the_write_confirmation_and_cancel_starts_nothing(window, english, tmp_path):
    ui = window()
    i18n.configure('en')  # the window applies the saved language; the warning text is built on click
    write_row(ui.look_editor, look_file(tmp_path / 'poor.a7look', mae=6.0, p95=20.0, name='Weak'), 3)
    with patch.object(W.QMessageBox, 'question', return_value=W.QMessageBox.Cancel) as asked, \
            patch.object(jobs, 'new_job') as new:
        ui.look_button.click()
    new.assert_not_called()
    assert asked.call_count == 1
    title, text = asked.call_args.args[1:3]
    assert title == 'Fit warning' and 'Custom 3' in text and 'poor' in text and not HAN.search(title + text)


def test_accepting_the_fit_warning_continues_to_the_write_confirmation(window, tmp_path):
    ui = window()
    write_row(ui.look_editor, look_file(tmp_path / 'unknown.a7look', name='Unmeasured'), 3)
    answers = [W.QMessageBox.Yes, W.QMessageBox.Cancel]
    with patch.object(W.QMessageBox, 'question', side_effect=answers) as asked, patch.object(jobs, 'new_job') as new:
        ui.look_button.click()
    new.assert_not_called()
    assert asked.call_count == 2


def test_good_fits_go_straight_to_the_write_confirmation(window, tmp_path):
    ui = window()
    write_row(ui.look_editor, look_file(tmp_path / 'good.a7look', mae=2.0, p95=7.0), 3)
    with patch.object(W.QMessageBox, 'question', return_value=W.QMessageBox.Cancel) as asked, \
            patch.object(jobs, 'new_job'):
        ui.look_button.click()
    assert asked.call_count == 1 and '3' in asked.call_args.args[2]
    assert asked.call_args.args[1] != i18n.tr('拟合提醒')


def test_one_click_setup_with_own_looks_checks_their_fit(window, tmp_path):
    ui = window()
    ui.setup_presets.setChecked(False)
    ui.fields['setup_look_2'].setText(str(look_file(tmp_path / 'poor.a7look', mae=6.0, p95=20.0)))
    with patch.object(ui, 'drivers_first', return_value=True), \
            patch.object(W.QMessageBox, 'question', return_value=W.QMessageBox.Cancel) as asked, \
            patch.object(jobs, 'new_job') as new:
        ui.launch('setup_all', ui.setup_args())
    new.assert_not_called()
    assert asked.call_args.args[1] == i18n.tr('拟合提醒')


def photo(path):
    Image.fromarray(np.full((20, 30, 3), 120, np.uint8)).save(path)
    return path


def wait(dialog, seconds=10):
    end = time.monotonic() + seconds
    while dialog.busy() and time.monotonic() < end:
        W.QApplication.processEvents(); time.sleep(.01)
    W.QApplication.processEvents()
    assert not dialog.busy()


def fake_render(document, image, output, **_):
    pixels = np.asarray(Image.open(image).convert('RGB'))
    Image.fromarray(np.hstack([pixels, pixels])).save(output)
    return dict(output=str(output), panels=[dict(role='photo', pixels=pixels), dict(role='camera', pixels=255 - pixels)])


def test_preview_shows_each_returned_panel_with_its_caption_and_can_be_saved(app, english, tmp_path):
    dialog = PreviewDialog(look_file(tmp_path / 'look.a7look', mae=2.0, p95=7.0), cache=tmp_path / 'cache',
                           render=fake_render)
    assert not dialog.save.isEnabled()
    dialog.start(photo(tmp_path / 'shot.png')); wait(dialog)
    shown = {role: not panel.isHidden() for role, panel in dialog.panels.items()}
    assert shown == {'photo': True, 'source': False, 'camera': True}
    assert dialog.panels['camera'].image.pixmap().width() > 0
    assert dialog.save.isEnabled()
    with patch.object(W.QFileDialog, 'getSaveFileName', return_value=(str(tmp_path / 'saved.png'), '')):
        dialog.save.click()
    assert Image.open(tmp_path / 'saved.png').size == (60, 20)
    texts = [dialog.windowTitle(), dialog.status.text()] + [p.caption.text() for p in dialog.panels.values()] + \
            [b.text() for b in dialog.findChildren(W.QAbstractButton)]
    assert not any(HAN.search(text) for text in texts)


def test_a_failed_preview_reports_the_error_and_allows_another_photo(app, english, tmp_path):
    def broken(*_, **__):
        raise ValueError('cannot identify image file')
    dialog = PreviewDialog(look_file(tmp_path / 'look.a7look'), cache=tmp_path / 'cache', render=broken)
    dialog.start(tmp_path / 'not-a-photo.png'); wait(dialog)
    assert dialog.status.text() == 'Preview failed: cannot identify image file'
    assert dialog.choose.isEnabled() and not dialog.save.isEnabled()


def test_the_preview_renders_through_the_look_preview_engine_with_the_given_cache(app, tmp_path):
    seen = {}
    def spy(document, image, output, **options):
        seen.update(options, name=document['name'], image=image)
        return fake_render(document, image, output)
    with patch('looktool.lookpreview.render', spy):
        dialog = PreviewDialog(look_file(tmp_path / 'look.a7look', name='Spy'), cache=tmp_path / 'cache')
        dialog.start(photo(tmp_path / 'shot.png')); wait(dialog)
    assert seen == dict(cache=tmp_path / 'cache', name='Spy', image=tmp_path / 'shot.png')


def test_window_preview_opens_the_dialog_with_the_app_cache(window, tmp_path):
    ui = window()
    path = look_file(tmp_path / 'look.a7look', mae=2.0, p95=7.0)
    with patch('desktopapp.lookviews.PreviewDialog.exec') as shown:
        ui.preview_look(str(path))
    shown.assert_called_once()
    dialog = ui.findChild(PreviewDialog)
    assert dialog.cache == Path(os.environ['A7C2_DESKTOP_DATA']) / 'preview-cache'


def test_window_reports_an_unreadable_look_instead_of_previewing(window, tmp_path):
    ui = window()
    with patch.object(W.QMessageBox, 'warning') as warned, patch('desktopapp.lookviews.PreviewDialog.exec') as shown:
        ui.preview_look(str(tmp_path / 'missing.a7look'))
    warned.assert_called_once(); shown.assert_not_called()


def test_window_library_reports_an_empty_or_broken_library(window, tmp_path):
    ui = window()
    with patch('desktopapp.looklibrary.location', return_value=tmp_path / 'absent'), \
            patch.object(W.QMessageBox, 'information') as told:
        ui.film_library_dialog()
    told.assert_called_once()
    broken = tmp_path / 'broken'; broken.mkdir(); (broken / 'catalog.json').write_text('{}')
    with patch('desktopapp.looklibrary.location', return_value=broken), \
            patch.object(W.QMessageBox, 'warning') as warned:
        ui.film_library_dialog()
    warned.assert_called_once()


def test_restore_rows_are_not_fit_checked(window, tmp_path):
    ui = window()
    ui.look_editor.add_row(1)
    write_row(ui.look_editor, look_file(tmp_path / 'poor.a7look', mae=6.0, p95=20.0, name='Weak'), 2)
    with patch.object(W.QMessageBox, 'question', return_value=W.QMessageBox.Cancel) as asked, \
            patch.object(jobs, 'new_job'):
        ui.look_button.click()
    tr = i18n.tr
    assert asked.call_args.args[1:3] == (tr('拟合提醒'),
        tr('以下外观在机内的拟合较差或未知，相机效果可能与原外观明显不同。建议先预览。\n') +
        tr('自订 %s：%s（拟合%s）') % (2, 'Weak', tr('较差')) + tr('\n仍要继续？'))
