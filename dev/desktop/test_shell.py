"""Window chrome building blocks: confirmations, sidebar, groups and rows, banner, status area, Settings."""
from unittest.mock import patch

import pytest
from PySide6 import QtCore, QtGui, QtWidgets as W

from desktopapp import shell, theme


@pytest.fixture
def app():
    return W.QApplication.instance() or W.QApplication([])


def answer_with(choose):
    """Stand in for QMessageBox.exec: record the box, then click the button choose(box) picks."""
    shown = []

    def run(box):
        shown.append(box)
        choose(box).click()
        return 0
    return shown, run


def verb_button(box):
    return next(button for button in box.buttons() if box.buttonRole(button) == W.QMessageBox.AcceptRole)


def test_ask_is_true_only_when_the_verb_is_clicked(app):
    parent = W.QWidget()
    shown, run = answer_with(verb_button)
    with patch.object(W.QMessageBox, 'exec', autospec=True, side_effect=run):
        assert shell.ask(parent, 'Write to the camera?', 'Custom 3: Portra', 'Write to Camera') is True
    shown, run = answer_with(lambda box: box.button(W.QMessageBox.Cancel))
    with patch.object(W.QMessageBox, 'exec', autospec=True, side_effect=run):
        assert shell.ask(parent, 'Write to the camera?', 'Custom 3: Portra', 'Write to Camera') is False


def test_ask_is_a_sheet_with_a_verb_button_and_no_default(app):
    parent = W.QWidget()
    shown, run = answer_with(lambda box: box.button(W.QMessageBox.Cancel))
    with patch.object(W.QMessageBox, 'exec', autospec=True, side_effect=run):
        shell.ask(parent, 'Write to the camera?', 'Body text', 'Write to Camera', details='raw log')
    box = shown[0]
    assert box.windowModality() == QtCore.Qt.WindowModal
    assert box.icon() == W.QMessageBox.Warning
    assert (box.text(), box.informativeText(), box.detailedText()) == ('Write to the camera?', 'Body text', 'raw log')
    assert verb_button(box).text() == 'Write to Camera'
    assert box.defaultButton() is box.button(W.QMessageBox.Cancel)  # Return must not confirm a write
    assert not verb_button(box).autoDefault()
    assert box.escapeButton() is box.button(W.QMessageBox.Cancel)


def test_return_cancels_a_confirmation_rather_than_writing(app):
    from PySide6 import QtTest
    parent = W.QWidget()
    parent.show()

    def press_return(box):
        box.show()
        QtTest.QTest.keyClick(box, QtCore.Qt.Key_Return)
        return 0
    try:
        with patch.object(W.QMessageBox, 'exec', autospec=True, side_effect=press_return):
            assert shell.ask(parent, 'Write to the camera?', 'Custom 3', 'Write to Camera') is False
    finally:
        parent.close()


def test_ask_disposes_of_each_answered_sheet(app):
    parent = W.QWidget()
    shown, run = answer_with(verb_button)
    with patch.object(W.QMessageBox, 'exec', autospec=True, side_effect=run):
        for _ in range(3):
            shell.ask(parent, 'Title', 'Text', 'Go')
    app.sendPostedEvents(None, QtCore.QEvent.DeferredDelete)
    assert parent.findChildren(W.QMessageBox) == []


def test_ask_disposes_of_the_sheet_when_showing_it_fails(app):
    parent = W.QWidget()
    with patch.object(W.QMessageBox, 'exec', side_effect=RuntimeError('no display')), pytest.raises(RuntimeError):
        shell.ask(parent, 'Title', 'Text', 'Go')
    app.sendPostedEvents(None, QtCore.QEvent.DeferredDelete)
    assert parent.findChildren(W.QMessageBox) == []


@pytest.mark.parametrize('name', sorted(shell.ICONS))
def test_every_icon_renders_crisp_in_the_given_colour(app, name):
    pixmap = shell.icon_pixmap(name, '#FF0000', size=16, ratio=2.0)
    assert (pixmap.width(), pixmap.height(), pixmap.devicePixelRatio()) == (32, 32, 2.0)
    image = pixmap.toImage()
    inked = [image.pixelColor(x, y) for x in range(32) for y in range(32) if image.pixelColor(x, y).alpha() > 200]
    assert inked, name
    assert all(colour.red() > 200 and colour.green() < 60 and colour.blue() < 60 for colour in inked)


def test_sidebar_keeps_one_row_per_page_with_section_titles_above(app):
    nav = shell.sidebar([('Setup', 'One-Click Install', 'home'), (None, 'Connection', 'connection'),
                         ('Camera', 'FL2 / FL3', 'film')])
    assert nav.objectName() == 'sidebar' and nav.width() == theme.SIDEBAR_WIDTH
    assert [nav.item(i).text() for i in range(nav.count())] == ['One-Click Install', 'Connection', 'FL2 / FL3']
    assert [nav.item(i).data(shell.SECTION) for i in range(nav.count())] == ['Setup', None, 'Camera']
    assert nav.item(1).toolTip() == 'Connection' and nav.item(1).data(shell.ICON) == 'connection'
    delegate, option = nav.itemDelegate(), W.QStyleOptionViewItem()
    option.rect = QtCore.QRect(0, 0, 200, 40)
    heights = [delegate.sizeHint(option, nav.model().index(i, 0)).height() for i in range(3)]
    assert heights == [shell.ROW + shell.HEADER, shell.ROW, shell.ROW + shell.HEADER]


@pytest.mark.parametrize('state', [W.QStyle.State_None, W.QStyle.State_Selected,
                                   W.QStyle.State_Selected | W.QStyle.State_Active])
def test_sidebar_rows_paint_in_every_selection_state(app, state):
    nav = shell.sidebar([('Setup', 'A very long label that has to be elided to fit', 'home')])
    option = W.QStyleOptionViewItem()
    option.rect, option.state, option.font = QtCore.QRect(0, 0, 200, shell.ROW + shell.HEADER), state, nav.font()
    image = QtGui.QImage(200, shell.ROW + shell.HEADER, QtGui.QImage.Format_ARGB32)
    image.fill(QtCore.Qt.transparent)
    painter = QtGui.QPainter(image)
    nav.itemDelegate().paint(painter, option, nav.model().index(0, 0))
    painter.end()
    selection = image.pixelColor(4, shell.HEADER + shell.ROW // 2)  # inside the row, left of the icon
    if state & W.QStyle.State_Selected:
        wanted = QtGui.QColor(theme.color('accent_fill' if state & W.QStyle.State_Active else 'sel_inactive'))
        assert max(abs(a - b) for a, b in zip(selection.getRgb()[:3], wanted.getRgb()[:3])) <= 2
        assert selection.alpha() == 255
    else:
        assert selection.alpha() == 0
    assert image.pixelColor(4, 4).alpha() == 0  # the section title area carries no selection


def test_group_draws_hairlines_between_rows_only(app):
    group = shell.Group()
    for name in ('first', 'second', 'third'):
        group.add(W.QLabel(name))
    rows = [group.rows.itemAt(i).widget() for i in range(group.rows.count())]
    assert [row.property('row') for row in rows] == ['first', True, True]
    assert group.property('group') is True


def test_action_row_hides_empty_help_and_keeps_a_live_status_label(app):
    button = W.QPushButton('Detect')
    row = shell.ActionRow('Detect camera', '', [button])
    assert row.help.isHidden()
    assert row.controls.itemAt(0).widget() is button
    live = W.QLabel('Not checked yet')
    row = shell.ActionRow('Camera', live)
    assert row.help is live and live.property('role') == 'callout' and not live.isHidden()


def test_check_row_indents_help_under_the_checkbox_label(app):
    row = shell.CheckRow(W.QCheckBox('Keep backups'), 'Saved in the task folder.')
    assert row.help.text() == 'Saved in the task folder.' and row.help.contentsMargins().left() == 20
    assert shell.CheckRow(W.QCheckBox('x')).help.isHidden()


def test_section_puts_a_headline_above_a_new_group(app):
    holder = W.QWidget()
    layout = W.QVBoxLayout(holder)
    group = shell.section(layout, 'Checks')
    heading = layout.itemAt(0).widget()
    assert (heading.text(), heading.property('role')) == ('Checks', 'headline')
    assert layout.itemAt(1).widget() is group
    shell.section(layout, '')
    assert layout.count() == 3  # no empty headline


@pytest.mark.parametrize('kind', ['info', 'warning', 'danger', 'success'])
def test_banner_kinds_show_a_glyph_and_colour(app, kind):
    banner = shell.Banner()
    banner.set_kind(kind)
    assert banner.property('banner') == kind
    assert not banner.glyph.isHidden() and not banner.glyph.pixmap().isNull()
    assert banner.text.property('role') is None


def test_plain_banner_is_quiet_text_without_a_box(app):
    banner = shell.Banner()
    banner.set_kind('danger')
    banner.set_kind('')
    assert banner.property('banner') is None
    assert banner.glyph.isHidden()
    assert banner.text.property('role') == 'callout'
    assert banner.layout().contentsMargins().top() == 0


def test_status_area_log_is_a_disclosure(app):
    area = shell.StatusArea()
    assert area.log.isHidden() and area.toggle.text() == '显示日志'
    area.toggle.click()
    assert not area.log.isHidden() and area.toggle.text() == '隐藏日志'
    assert area.toggle.arrowType() == QtCore.Qt.DownArrow
    area.show_log(False)
    assert area.log.isHidden() and not area.toggle.isChecked()
    area.show_log(True)
    assert area.toggle.isChecked() and not area.log.isHidden()
    assert area.stop.isHidden() and not area.stop.isEnabled()
    assert area.log.isReadOnly() and area.log.font().families() == theme.mono_families()


def test_settings_holds_the_language_firmware_and_version(app):
    combo = W.QComboBox()
    dialog = shell.SettingsDialog(None, combo, '2.01', '3.0.3 Desktop development build')
    assert combo.window() is dialog
    labels = [label.text() for label in dialog.findChildren(W.QLabel)]
    assert '2.01' in labels and '3.0.3 Desktop development build' in labels
    buttons = dialog.findChild(W.QDialogButtonBox)
    assert buttons.button(W.QDialogButtonBox.Close) is not None
