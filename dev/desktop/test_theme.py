"""The design system: tokens, contrast, the application style sheet, palette and fonts."""
import re
from unittest.mock import patch

import pytest
from PySide6 import QtGui, QtWidgets as W

from desktopapp import theme

SCHEMES = ('light', 'dark')
# Every text colour the style sheet or the painted widgets put on a background.
TEXT_PAIRS = ([('text', bg) for bg in ('page', 'group', 'field', 'control', 'sidebar', 'log', 'sel_inactive',
                                        'sel_text', 'info_bg', 'warning_bg', 'danger_bg', 'success_bg')]
              + [('text2', bg) for bg in ('page', 'group', 'sidebar', 'field')]
              + [('accent_text', bg) for bg in ('page', 'group', 'info_bg')]
              + [('on_accent', 'accent_fill'), ('on_accent', 'accent_fill_pressed')]
              + [(kind, bg) for kind in ('danger', 'warning', 'success', 'info')
                 for bg in (kind + '_bg', 'page', 'group')])


def luminance(value):
    channels = [int(value.lstrip('#')[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    linear = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def contrast(a, b):
    high, low = sorted((luminance(a), luminance(b)), reverse=True)
    return (high + 0.05) / (low + 0.05)


@pytest.fixture
def app():
    return W.QApplication.instance() or W.QApplication([])


@pytest.fixture
def restore_theme(app):
    """apply() changes the whole application: put the real appearance back afterwards."""
    yield app
    app.setProperty('a7c2_theme', None)
    theme.apply(app)


def test_light_and_dark_define_the_same_tokens():
    assert set(theme.COLORS['light']) == set(theme.COLORS['dark'])


@pytest.mark.parametrize('scheme', SCHEMES)
def test_every_text_colour_meets_wcag_aa_on_its_background(scheme):
    tokens = theme.COLORS[scheme]
    failing = ['%s on %s: %.2f' % (fg, bg, contrast(tokens[fg], tokens[bg])) for fg, bg in TEXT_PAIRS
               if contrast(tokens[fg], tokens[bg]) < 4.5]
    assert failing == []


@pytest.mark.parametrize('scheme', SCHEMES)
def test_style_sheet_fills_every_placeholder_with_the_scheme_tokens(app, scheme):
    sheet = theme.stylesheet(scheme)
    assert '$' not in sheet
    assert 'background:%s' % theme.COLORS[scheme]['page'] in sheet
    assert 'min-height:%dpx' % (theme.CONTROL_HEIGHT - 2) in sheet


@pytest.mark.parametrize('scheme', SCHEMES)
def test_style_sheet_images_exist(app, scheme):
    for path in re.findall(r'url\("([^"]+)"\)', theme.stylesheet(scheme)):
        assert theme.Path(path).is_file(), path


def test_icons_are_tinted_per_colour_and_reused(app):
    first = theme.tinted('chevron-down.svg', '#123456')
    second = theme.tinted('chevron-down.svg', '#ABCDEF')
    assert first != second
    assert '#123456' in theme.Path(first).read_text(encoding='utf-8')
    assert '#ABCDEF' in theme.Path(second).read_text(encoding='utf-8')
    assert '#5d6a7e' not in theme.Path(second).read_text(encoding='utf-8')
    assert theme.tinted('chevron-down.svg', '#123456') == first


@pytest.mark.parametrize('scheme', SCHEMES)
def test_palette_follows_the_tokens(app, scheme):
    palette, tokens = theme.palette(scheme), theme.COLORS[scheme]
    role, group = QtGui.QPalette.ColorRole, QtGui.QPalette.ColorGroup
    assert palette.color(role.Window).name().upper() == tokens['page']
    assert palette.color(role.Text).name().upper() == tokens['text']
    assert palette.color(role.Highlight).name().upper() == tokens['accent_fill']
    assert palette.color(group.Disabled, role.ButtonText).name().upper() == tokens['text3']


def test_color_reads_the_current_appearance(app):
    with patch.object(theme, 'mode', return_value='dark'):
        assert theme.color('text') == theme.COLORS['dark']['text']
    assert theme.color('text', 'light') == theme.COLORS['light']['text']


def test_apply_styles_the_application_for_the_appearance(restore_theme):
    app = restore_theme
    app.setProperty('a7c2_theme', None)
    with patch.object(theme, 'mode', return_value='dark'):
        assert theme.apply(app) == 'dark'
    assert app.styleSheet() == theme.stylesheet('dark')
    assert app.palette().color(QtGui.QPalette.ColorRole.Window).name().upper() == theme.COLORS['dark']['page']
    assert app.font().pixelSize() == theme.TYPE['body'][0]


def test_apply_skips_work_when_the_appearance_is_already_applied(restore_theme):
    app = restore_theme
    app.setProperty('a7c2_theme', None)
    with patch.object(theme, 'mode', return_value='light'):
        theme.apply(app)
        with patch.object(W.QApplication, 'setStyleSheet') as sheet:
            assert theme.apply(app) == 'light'
        sheet.assert_not_called()
    with patch.object(theme, 'mode', return_value='dark'), patch.object(W.QApplication, 'setStyleSheet') as sheet:
        theme.apply(app)
    sheet.assert_called_once_with(theme.stylesheet('dark'))


def test_fusion_is_set_on_the_first_apply_only(restore_theme):
    # Under a style sheet app.style() is Qt's wrapper, so a name check would reset the style
    # (and restyle every widget) on each appearance change.
    app = restore_theme
    app.setProperty('a7c2_theme', None)
    with patch.object(W.QApplication, 'setStyle') as style, patch.object(theme, 'mode', return_value='light'):
        theme.apply(app)
    style.assert_called_once_with('Fusion')
    with patch.object(W.QApplication, 'setStyle') as style, patch.object(theme, 'mode', return_value='dark'):
        theme.apply(app)
    style.assert_not_called()


def test_the_application_style_is_fusion_underneath_the_sheet(app):
    sheet = app.styleSheet()
    app.setStyleSheet('')
    try:
        assert app.style().name() == 'fusion'
    finally:
        app.setStyleSheet(sheet)


def test_ui_fonts_lead_with_the_system_face_and_list_only_installed_families(app):
    families = theme.ui_families()
    installed = set(QtGui.QFontDatabase.families())
    if theme.sys.platform == 'darwin':
        # The system face is a private family (.AppleSystemUIFont) that families() does not list.
        assert families[0] == QtGui.QFontDatabase.systemFont(QtGui.QFontDatabase.GeneralFont).family()
        families = families[1:]
    assert all(family in installed for family in families)


def test_log_font_is_monospaced_at_the_mono_size(app):
    font = theme.mono_font()
    assert font.pixelSize() == theme.TYPE['mono'][0]
    assert QtGui.QFontInfo(font).fixedPitch()


def test_repolish_applies_a_changed_role(app):
    label = W.QLabel('x')
    label.setStyleSheet('QLabel[role="title1"] {font-size:22px;}')
    label.ensurePolished()
    label.setProperty('role', 'title1')
    theme.repolish(label)
    assert label.font().pixelSize() == 22
