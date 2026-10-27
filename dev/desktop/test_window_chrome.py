"""The main window's chrome: page header, status states, Settings and Help menus, appearance changes."""
from unittest.mock import patch

import pytest
from PySide6 import QtCore, QtGui, QtWidgets as W

from desktopapp import connectionguide, i18n, lookeditor, shell, theme, window as window_module
from desktopapp.paths import load_settings, save_settings
from guihelpers import HAN


def menu_actions(ui, title):
    # Found through the menu bar's children: a QMenu wrapper from QAction.menu() can outlive its object.
    return next(menu for menu in ui.menuBar().findChildren(W.QMenu) if menu.title() == title).actions()


def test_each_sidebar_row_shows_its_page_title_and_description_in_the_header(window):
    ui = window('en')
    assert ui.nav.count() == ui.pages.count() == len(ui.page_meta) == len(window_module.NAVIGATION)
    for index in range(ui.nav.count()):
        ui.nav.setCurrentRow(index)
        title, detail = ui.page_meta[index]
        assert ui.pages.currentIndex() == index
        assert ui.page_title.text() == title and title and not HAN.search(title)
        assert ui.page_detail.text() == detail
        assert ui.page_detail.isHidden() == (not detail)


def test_sidebar_sections_group_the_pages(window):
    ui = window('en')
    sections = [ui.nav.item(i).data(shell.SECTION) for i in range(ui.nav.count())]
    assert [s for s in sections if s] == ['Setup', 'Camera', 'Experimental']
    assert all(ui.nav.item(i).data(shell.ICON) in shell.ICONS for i in range(ui.nav.count()))


@pytest.mark.parametrize('kind', ['', 'info', 'success', 'warning', 'danger'])
def test_progress_and_stop_show_only_while_a_task_runs(window, kind):
    ui = window()
    ui.set_state(kind)
    assert ui.status_area.banner.property('banner') == (kind or None)
    assert ui.progress.isHidden() == (kind != 'info')
    assert ui.stop.isHidden() == (kind != 'info')


def test_a_failure_opens_the_log_and_others_leave_it_as_the_user_set_it(window):
    ui = window()
    assert ui.log.isHidden()
    ui.set_state('success')
    assert ui.log.isHidden()
    ui.set_state('danger')
    assert not ui.log.isHidden() and ui.status_area.toggle.isChecked()


def test_settings_lives_in_the_app_menu_with_the_standard_shortcut(window):
    ui = window('en')
    settings = next(action for action in menu_actions(ui, 'Edit') if action.text() == 'Settings…')
    assert settings.menuRole() == QtGui.QAction.PreferencesRole
    assert settings.shortcut() == QtGui.QKeySequence(QtGui.QKeySequence.Preferences)
    with patch.object(ui.settings_dialog, 'open') as opened:
        settings.trigger()
    opened.assert_called_once()
    assert ui.language.window() is ui.settings_dialog


def test_help_menu_opens_each_guide(window):
    with patch.object(window_module.Window, 'show_reload_guide') as reload_guide, \
            patch.object(window_module.Window, 'show_look_format_guide') as format_guide:
        ui = window('en')
        actions = menu_actions(ui, 'Help')
        assert [action.text() for action in actions] == ['Before You Connect…', 'How to Restart the Camera…',
                                                         'Supported LUT Formats…']
        with patch.object(W.QMessageBox, 'information') as notice:
            actions[0].trigger()
        actions[1].trigger()
        actions[2].trigger()
    assert notice.call_args.args[1:] == (i18n.tr(connectionguide.TITLE), i18n.tr(connectionguide.TEXT))
    assert not HAN.search(''.join(notice.call_args.args[1:]))
    reload_guide.assert_called_once()
    format_guide.assert_called_once()


def test_connection_notice_shows_on_first_launch_only(window, tmp_path):
    first = window()
    assert first.connection_notice_due() is True
    assert load_settings()['connection_notice_seen'] is True
    assert first.connection_notice_due() is False
    assert window().connection_notice_due() is False  # a later launch reads the saved setting


def test_launch_without_a_due_notice_shows_no_alert(monkeypatch):
    from unittest.mock import Mock
    app = Mock()
    app.exec.return_value = 0
    with patch.object(window_module.W.QApplication, 'instance', return_value=app), \
            patch.object(window_module, 'Window') as ctor, \
            patch.object(window_module.QtCore.QTimer, 'singleShot') as timer, \
            patch.object(window_module.sys, 'argv', ['A7C2Tools']):
        ctor.return_value.connection_notice_due.return_value = False
        assert window_module.main() == 0
    timer.assert_not_called()


def test_settings_round_trip_through_the_settings_file(window, tmp_path):
    window()  # points the data folder at tmp_path
    save_settings({'language': 'en', 'sound_source': '/a/b 文件.wav'})
    assert load_settings() == {'language': 'en', 'sound_source': '/a/b 文件.wav'}


def test_appearance_change_restyles_the_app_and_painted_parts(window):
    ui = window()
    app = W.QApplication.instance()
    try:
        with patch.object(theme, 'mode', return_value='dark'), \
                patch.object(ui.status_area.banner, 'refresh') as banner:
            app.styleHints().colorSchemeChanged.emit(QtGui.Qt.ColorScheme.Dark)
        assert app.styleSheet() == theme.stylesheet('dark')
        banner.assert_called()
    finally:
        app.setProperty('a7c2_theme', None)
        theme.apply(app)


def rendered(widget):
    """The widget alone on a white canvas, whatever its parent paints behind it."""
    image = QtGui.QImage(widget.size(), QtGui.QImage.Format_ARGB32)
    image.fill(QtGui.QColor('white'))
    widget.render(image, QtCore.QPoint(), QtGui.QRegion(), W.QWidget.RenderFlag.DrawChildren)
    return image


def test_look_editor_menus_draw_only_the_themed_arrow(window):
    window()  # applies the application style sheet
    row = lookeditor.Operation(3)
    for combo in (row.slot, row.action):
        plain = W.QComboBox()
        plain.addItems([combo.itemText(i) for i in range(combo.count())])
        plain.setCurrentIndex(combo.currentIndex())
        plain.setFixedWidth(combo.width())
        for each in (plain, combo):
            each.resize(each.width(), theme.CONTROL_HEIGHT)
        assert rendered(combo) == rendered(plain)


@pytest.mark.parametrize('platform, build', [('darwin', 'Desktop development build'), ('win32', 'Windows test build')])
def test_settings_shows_the_version_and_build(window, platform, build):
    from desktopapp import VERSION
    ui = window('en', platform=platform)
    texts = [label.text() for label in ui.settings_dialog.findChildren(W.QLabel)]
    assert '%s (%s)' % (VERSION, build) in texts, texts


def test_confirmation_titles_are_bold_like_macos_alerts(window):
    window()  # applies the application style sheet
    box = W.QMessageBox(W.QMessageBox.Warning, 'Write to the camera?', 'Details', W.QMessageBox.Cancel)
    box.setInformativeText('More details')
    box.ensurePolished()
    title = box.findChild(W.QLabel, 'qt_msgbox_label')
    title.ensurePolished()
    assert title.font().bold()
    informative = box.findChild(W.QLabel, 'qt_msgbox_informativelabel')
    informative.ensurePolished()
    assert not informative.font().bold()


@pytest.mark.parametrize('opener', ['compiler_dialog', 'show_look_format_guide', 'show_zadig_guide', 'film_library_dialog'])
def test_closed_dialogs_are_released_rather_than_kept_by_the_window(window, opener, monkeypatch):
    # The window owns every dialog parented to it, so each opening used to leave one behind.
    from desktopapp import looklibrary
    ui = window('en', platform='win32')
    if opener == 'film_library_dialog':
        monkeypatch.setattr(looklibrary, 'catalog', lambda: [dict(
            id='portra400', name='Portra 400', kind='negative', path=lookeditor.Path('x.a7look'), preview=False,
            fit={'rating': 'fair', 'mae': 3.0, 'p95': 9.0}, notes='', modification='m', shareable=True, swatches=None,
            source={'project': 'p', 'author': 'a', 'url': 'https://example.org', 'licence': 'CC0'})])
    with patch.object(W.QDialog, 'exec', return_value=0):
        for _ in range(2):
            getattr(ui, opener)()
    W.QApplication.sendPostedEvents(None, QtCore.QEvent.DeferredDelete)
    assert [dialog for dialog in ui.findChildren(W.QDialog) if dialog is not ui.settings_dialog] == []


def test_ask_and_modal_release_their_dialogs(window):
    ui = window()
    with patch.object(W.QMessageBox, 'exec', return_value=0):
        shell.ask(ui, 'Title', 'Text', 'Go')
        ui.ask_drivers_first()
    W.QApplication.sendPostedEvents(None, QtCore.QEvent.DeferredDelete)
    assert ui.findChildren(W.QMessageBox) == []


def test_the_window_keeps_working_after_the_compiler_dialog_closes(window):
    # Its fields belong to the dialog, which is deleted on close: the window must not keep them.
    from desktopapp.paths import load_settings
    ui = window('en')

    def type_and_close(dialog):
        ui.fields['compile_name'].setText('My film look')
        return 0
    with patch.object(W.QDialog, 'exec', autospec=True, side_effect=type_and_close):
        ui.compiler_dialog()
    W.QApplication.sendPostedEvents(None, QtCore.QEvent.DeferredDelete)
    assert not any(key.startswith('compile_') for key in ui.fields)
    assert load_settings()['compile_name'] == 'My film look'  # kept for the next opening
    ui.findChild(W.QPushButton, 'action_sound_import').click()  # launch() reads every field
    assert ui.current_job is not None
    shown = []
    with patch.object(W.QDialog, 'exec', autospec=True, side_effect=lambda dialog: shown.append(
            ui.fields['compile_name'].text()) or 0):
        ui.compiler_dialog()
    assert shown == ['My film look']  # the next opening starts from the saved value


@pytest.mark.parametrize('kind', ['info', 'warning'])
def test_every_banner_follows_an_appearance_change(window, kind):
    ui = window('en')
    app = W.QApplication.instance()
    banners = [banner for banner in ui.findChildren(shell.Banner) if banner.kind == kind]
    assert banners
    try:
        with patch.object(theme, 'mode', return_value='dark'):
            ui.restyle()
            wanted = QtGui.QColor(theme.color(kind))
        for banner in banners:
            image = banner.glyph.pixmap().toImage()
            inked = [image.pixelColor(x, y) for x in range(image.width()) for y in range(image.height())
                     if image.pixelColor(x, y).alpha() > 200]
            assert inked and all(abs(c.red() - wanted.red()) < 8 and abs(c.blue() - wanted.blue()) < 8 for c in inked)
    finally:
        app.setProperty('a7c2_theme', None)
        theme.apply(app)


def test_a_task_that_stops_partway_keeps_its_progress_on_screen(window):
    ui = window()
    ui.progress.setValue(70)
    ui.set_state('warning')
    assert not ui.progress.isHidden()
    ui.progress.setValue(100)
    ui.set_state('warning')
    assert ui.progress.isHidden()
    ui.progress.setValue(70)
    ui.set_state('success')
    assert ui.progress.isHidden()


def test_the_macos_connection_page_says_terminal_asks_for_the_password(window):
    texts = lambda ui: ' '.join(b.text.text() for b in ui.findChildren(shell.Banner))
    assert 'Terminal' in texts(window('en', platform='darwin'))
    assert 'Terminal' not in texts(window('en', platform='win32'))
