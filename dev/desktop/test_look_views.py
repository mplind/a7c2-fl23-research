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
from guihelpers import HAN
from looksamples import look_file


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.setenv('A7C2_DESKTOP_DATA', str(tmp_path / 'data'))
    return W.QApplication.instance() or W.QApplication([])


@pytest.fixture
def english():
    i18n.configure('en')
    yield
    i18n.configure('zh_CN')


def write_row(editor, path, slot=1):
    row = editor.add_row(slot)
    row.action.setCurrentIndex(1)
    row.set_file(str(path))
    return row


@pytest.mark.parametrize('mae,p95,expected', [
    (2.0, 7.0, 'Fit: good (MAE 2.0, P95 7.0)'),
    (4.0, 12.0, 'Fit: fair (MAE 4.0, P95 12.0)'),
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
    assert poor.fit.text().startswith('Fit: poor (MAE 6.0, P95 20.0)') and 'differ' in poor.fit.text()
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


PORTRA = ['#6C5043', '#BB9281', '#607FA2', '#616645', '#D8954D', '#313332', '#79797A', '#C0C2C5']


def library(tmp_path, swatches=(PORTRA, None)):
    folder = tmp_path / 'library'; folder.mkdir()
    entries = []
    for (slug, name, kind, mae, notes), colours in zip((('portra400', 'Portra 400', 'negative', 3.07, ''),
                                                        ('velvia100', 'Velvia 100', 'slide', 3.48,
                                                         'Slight cyan cast in deep shadows.')), swatches):
        look_file(folder / (slug + '.a7look'), mae=mae, p95=9.0, name=name)
        entries.append({'id': slug, 'name': name, 'kind': kind, 'file': slug + '.a7look',
                        'source': {'project': 'spektrafilm', 'author': 'Andrea Volpato',
                                   'url': 'https://github.com/andreavolpato/spektrafilm', 'licence': 'CC BY-SA 4.0'},
                        'modification': 'Baked to a 33^3 cube', 'shareable': True, 'notes': notes})
        if colours:
            entries[-1]['swatches'] = colours
    (folder / 'catalog.json').write_text(json.dumps({'schema': looklibrary.SCHEMA, 'looks': entries}))
    return looklibrary.catalog(folder)


def test_library_rows_name_each_look_and_read_out_its_kind_and_fit(app, english, tmp_path):
    from PySide6 import QtCore
    dialog = FilmLibraryDialog(library(tmp_path))
    assert [dialog.list.item(i).text() for i in range(dialog.list.count())] == ['Portra 400', 'Velvia 100']
    assert dialog.list.item(1).data(QtCore.Qt.AccessibleTextRole) == 'Velvia 100, Slide, Fit: fair'
    assert dialog.list.item(1).toolTip() == 'Velvia 100, Slide, Fit: fair'


def render_row(dialog, row, selected=False):
    from PySide6 import QtCore, QtGui
    option = W.QStyleOptionViewItem()
    option.rect = QtCore.QRect(0, 0, 330, dialog.list.itemDelegate().ROW)
    option.font = dialog.list.font()
    option.state = W.QStyle.State_Selected | W.QStyle.State_Active if selected else W.QStyle.State_None
    image = QtGui.QImage(option.rect.size(), QtGui.QImage.Format_ARGB32)
    image.fill(QtCore.Qt.transparent)
    painter = QtGui.QPainter(image)
    dialog.list.itemDelegate().paint(painter, option, dialog.list.model().index(row, 0))
    painter.end()
    return image


def test_library_rows_carry_the_looks_swatch_strip(app, english, tmp_path):
    from desktopapp import lookviews
    dialog = FilmLibraryDialog(library(tmp_path))
    image = render_row(dialog, 0)
    centres = lookviews.swatch_centres(dialog.list.itemDelegate().strip_rect(image.rect()), len(PORTRA))
    assert [image.pixelColor(point).name().upper() for point in centres] == PORTRA
    plain = render_row(dialog, 1)  # a look prepared without swatches draws no strip
    assert all(plain.pixelColor(point).alpha() == 0 for point in centres)
    assert not render_row(dialog, 0, selected=True).isNull()


def test_the_selected_look_shows_reference_colours_over_its_camera_rendering(app, english, tmp_path):
    dialog = FilmLibraryDialog(library(tmp_path))
    dialog.list.setCurrentRow(0)
    assert not dialog.strip.isHidden()
    assert dialog.strip.colours == PORTRA
    assert dialog.strip.references == ['#%02X%02X%02X' % rgb for _, rgb in looklibrary.REFERENCE]
    image = dialog.strip.grab().toImage()
    assert not image.isNull()
    dialog.list.setCurrentRow(1)
    assert dialog.strip.isHidden()


def test_library_buttons_follow_the_title_case_verbs(app, english, tmp_path):
    dialog = FilmLibraryDialog(library(tmp_path), notices=tmp_path)
    texts = sorted(button.text() for button in dialog.findChildren(W.QPushButton))
    assert texts == ['Add to List', 'Close', 'Licence Notices…', 'Preview on My Photo…']
    assert dialog.add.property('primary') is True


def test_library_lists_looks_and_shows_source_licence_and_notes(app, english, tmp_path):
    dialog = FilmLibraryDialog(library(tmp_path))
    dialog.list.setCurrentRow(1)
    details = dialog.details.toPlainText()
    for text in ('Velvia 100', 'spektrafilm by Andrea Volpato', 'CC BY-SA 4.0', 'Baked to a 33^3 cube',
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
    with patch('desktopapp.window.ask', return_value=False) as asked, \
            patch.object(jobs, 'new_job') as new:
        ui.look_button.click()
    new.assert_not_called()
    assert asked.call_count == 1
    title, text = asked.call_args.args[1:3]
    assert title == 'Some looks may not match on the camera' and 'Custom 3' in text and 'poor' in text and not HAN.search(title + text)


def test_accepting_the_fit_warning_continues_to_the_write_confirmation(window, tmp_path):
    ui = window()
    write_row(ui.look_editor, look_file(tmp_path / 'unknown.a7look', name='Unmeasured'), 3)
    answers = [True, False]
    with patch('desktopapp.window.ask', side_effect=answers) as asked, patch.object(jobs, 'new_job') as new:
        ui.look_button.click()
    new.assert_not_called()
    assert asked.call_count == 2


def test_good_fits_go_straight_to_the_write_confirmation(window, tmp_path):
    ui = window()
    write_row(ui.look_editor, look_file(tmp_path / 'good.a7look', mae=2.0, p95=7.0), 3)
    with patch('desktopapp.window.ask', return_value=False) as asked, \
            patch.object(jobs, 'new_job'):
        ui.look_button.click()
    assert asked.call_count == 1 and '3' in asked.call_args.args[2]
    assert asked.call_args.args[1] != i18n.tr('拟合提醒')


def test_one_click_setup_with_own_looks_checks_their_fit(window, tmp_path):
    ui = window()
    ui.setup_presets.setChecked(False)
    ui.fields['setup_look_2'].setText(str(look_file(tmp_path / 'poor.a7look', mae=6.0, p95=20.0)))
    with patch.object(ui, 'drivers_first', return_value=True), \
            patch('desktopapp.window.ask', return_value=False) as asked, \
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
    with patch('desktopapp.window.ask', return_value=False) as asked, \
            patch.object(jobs, 'new_job'):
        ui.look_button.click()
    tr = i18n.tr
    assert asked.call_args.args[1:3] == (tr('拟合提醒'),
        tr('以下外观在机内的拟合较差或未知，相机效果可能与原外观明显不同。\n') +
        tr('自订 %s：%s（拟合%s）') % (2, 'Weak', tr('较差')) + tr('\n可以预览的外观，建议先预览。') + tr('\n仍要继续？'))


def test_preview_needs_the_fitted_native_controls(app, tmp_path):
    editor = LookEditor()
    without = write_row(editor, look_file(tmp_path / 'old.a7look', mae=2.0, p95=7.0, controls=False), 1)
    unknown = write_row(editor, look_file(tmp_path / 'unknown.a7look'), 2)
    assert not without.preview.isEnabled() and unknown.preview.isEnabled()


def test_the_fit_warning_suggests_a_preview_only_when_one_is_possible(window, tmp_path):
    ui = window()
    write_row(ui.look_editor, look_file(tmp_path / 'old.a7look', controls=False), 3)
    with patch('desktopapp.window.ask', return_value=False) as asked, \
            patch.object(jobs, 'new_job'):
        ui.look_button.click()
    assert asked.call_args.args[1] == i18n.tr('拟合提醒')
    assert i18n.tr('\n可以预览的外观，建议先预览。') not in asked.call_args.args[2]


def test_library_preview_follows_the_selected_look(app, tmp_path):
    looks = library(tmp_path)
    looks[1] = dict(looks[1], preview=False)
    dialog = FilmLibraryDialog(looks)
    dialog.list.setCurrentRow(0)
    assert dialog.preview.isEnabled()
    dialog.list.setCurrentRow(1)
    assert not dialog.preview.isEnabled()


def test_a_closed_library_dialog_is_released(app, tmp_path):
    import gc, weakref
    dialog = FilmLibraryDialog(library(tmp_path))
    ref = weakref.ref(dialog)
    del dialog
    gc.collect()
    assert ref() is None


def test_a_preview_closed_mid_render_is_released_on_the_gui_thread(app, tmp_path):
    # Closing during a render used to leave the render thread holding the dialog's last
    # reference, so Qt destroyed the dialog and its timer on that thread and crashed.
    import gc, threading, weakref
    started, release = threading.Event(), threading.Event()
    def slow(document, image, output, **_):
        started.set()
        release.wait(10)
        return fake_render(document, image, output)
    dialog = PreviewDialog(look_file(tmp_path / 'look.a7look', mae=2.0, p95=7.0), cache=tmp_path / 'cache', render=slow)
    dialog.start(photo(tmp_path / 'shot.png'))
    assert started.wait(5)
    thread = next(t for t in threading.enumerate() if t.name == 'a7c2-preview')
    ref = weakref.ref(dialog)
    del dialog
    gc.collect()
    kept = ref()
    try:
        assert kept is None
    finally:
        release.set()
        thread.join(5)
        del kept  # if the render thread kept it, drop it here on the GUI thread, never there


def test_a_dcp_source_panel_is_captioned_as_a_dcp(app, english, tmp_path):
    def dcp_render(document, image, output, **_):
        result = fake_render(document, image, output)
        result['panels'].insert(1, dict(role='source', kind='dcp', pixels=result['panels'][0]['pixels']))
        return result
    dialog = PreviewDialog(look_file(tmp_path / 'look.a7look'), cache=tmp_path / 'cache', render=dcp_render)
    dialog.start(photo(tmp_path / 'shot.png')); wait(dialog)
    assert dialog.panels['source'].caption.text() == 'Original look (DCP)'


@pytest.mark.parametrize('colour,expected', [
    (dict(kind='converted', profile='Adobe RGB (1998)'), 'converted from Adobe RGB (1998) to sRGB'),
    (dict(kind='uncalibrated'), 'treated as sRGB'),
])
def test_the_preview_reports_how_the_photo_colours_were_handled(app, english, tmp_path, colour, expected):
    def coloured(document, image, output, **_):
        return dict(fake_render(document, image, output), colour=colour)
    dialog = PreviewDialog(look_file(tmp_path / 'look.a7look'), cache=tmp_path / 'cache', render=coloured)
    dialog.start(photo(tmp_path / 'shot.png')); wait(dialog)
    assert expected in dialog.status.text()


def unreadable(tmp_path):
    from test_looklibrary import malformed_look
    return malformed_look(tmp_path / 'bad.a7look', lambda d: d.update(raw_profile='x'))


def test_choosing_an_unreadable_look_updates_the_whole_row(app, english, tmp_path):
    editor = LookEditor()
    row = write_row(editor, look_file(tmp_path / 'good.a7look', mae=2.0, p95=7.0))
    changes = []
    editor.changed.connect(lambda: changes.append(True))
    row.set_file(str(unreadable(tmp_path)))
    assert row.fit.text().startswith('Cannot read this A7Look: ') and row.fit.property('warning')
    assert not row.preview.isEnabled() and row.file.text() == 'bad.a7look' and changes


def test_a_long_fit_message_is_shortened_with_the_full_text_in_its_tooltip(app, tmp_path):
    editor = LookEditor()
    row = write_row(editor, tmp_path / ('missing-' + 'x' * 200 + '.a7look'))
    assert len(row.fit.text()) <= 120 and row.fit.text().endswith('…')
    assert ('x' * 200) in row.fit.toolTip()


def test_previewing_an_unreadable_look_warns_instead_of_raising(window, tmp_path):
    ui = window()
    with patch.object(W.QMessageBox, 'warning') as warned, patch('desktopapp.lookviews.PreviewDialog.exec') as shown:
        ui.preview_look(str(unreadable(tmp_path)))
    warned.assert_called_once(); shown.assert_not_called()


def test_a_library_look_replaces_the_slots_custom_name(window, tmp_path):
    ui = window()
    first, second = library(tmp_path)
    row = ui.look_editor.add_row(4)
    row.action.setCurrentIndex(1); row.set_file(str(first['path'])); row.name.setText('Mine')
    assert ui.add_library_look(second, 4)
    assert ui.look_editor.values() == [dict(slot=4, action='write', path=str(second['path']), name='')]


def test_one_click_setup_refuses_an_unreadable_look_before_any_prompt(window, tmp_path):
    ui = window()
    ui.setup_presets.setChecked(False)
    ui.fields['setup_look_2'].setText(str(tmp_path / 'moved-away.a7look'))
    with patch.object(ui, 'drivers_first', side_effect=AssertionError('driver prompt shown')), \
            patch('desktopapp.window.ask') as asked, patch.object(W.QMessageBox, 'warning') as warned, \
            patch.object(jobs, 'new_job') as new:
        ui.launch('setup_all', ui.setup_args())
    asked.assert_not_called(); new.assert_not_called()
    warned.assert_called_once()
    assert 'moved-away.a7look' in warned.call_args.args[2]


PRESETS = Path(__file__).resolve().parents[2] / 'desktop-assets/presets/default-six-v1'


@pytest.mark.skipif(not PRESETS.is_dir(), reason='the built-in six are a distribution asset')
def test_one_click_setup_fit_checks_the_built_in_six(window):
    ui = window()
    ui.setup_presets.setChecked(True)
    checked = []
    with patch('desktopapp.looklibrary.fit_concerns', side_effect=lambda looks: checked.extend(looks) or []), \
            patch.object(ui, 'drivers_first', return_value=True), \
            patch('desktopapp.window.ask', return_value=False), patch.object(jobs, 'new_job'):
        ui.launch('setup_all', ui.setup_args())
    assert sorted(look['slot'] for look in checked) == [1, 2, 3, 4, 5, 6]


@pytest.mark.parametrize('scheme', ['light', 'dark'])
def test_swatches_have_an_edge_that_shows_on_the_page(app, english, tmp_path, scheme):
    # A near-black swatch must not vanish into a dark window, nor a pale one into a light window.
    from PySide6 import QtCore, QtGui
    from desktopapp import lookviews, theme
    with patch.object(theme, 'mode', return_value=scheme):
        background = QtGui.QColor(theme.color('group'))
        for colour in (background.name(), '#0B1213', '#F5F5F5'):
            image = QtGui.QImage(40, 40, QtGui.QImage.Format_ARGB32)
            image.fill(background)
            painter = QtGui.QPainter(image)
            lookviews.paint_swatches(painter, QtCore.QRect(10, 10, 0, 0), [colour], size=20)
            painter.end()
            edge = image.pixelColor(10, 20)  # on the swatch's left edge
            assert edge != background, (scheme, colour)
