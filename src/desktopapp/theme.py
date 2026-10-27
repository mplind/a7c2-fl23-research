"""The desktop design system: Apple-style tokens, one application style sheet and palette.

Values follow Apple's Human Interface Guidelines for macOS, measured against AppKit on
macOS 15 (system colours, 13 px body text, 28 px controls, hairlines instead of shadows);
where Apple and Material Design disagree, Apple wins on every platform. Widgets choose a
role through dynamic properties (role, kind, banner, badge, group) and never carry their
own style sheet, so one sheet and one palette restyle the whole app, light or dark.
"""
from pathlib import Path
import sys
import tempfile
from string import Template
from PySide6 import QtCore, QtGui, QtWidgets as W
from .paths import ROOT

# Light and dark tokens. Apple system colours; the few deviations (text2, accent_fill and the
# darkened status colours) keep every text pair at WCAG AA contrast.
COLORS = {
    'light': dict(
        page='#F6F6F6', sidebar='#EFEFEF', group='#FFFFFF', control='#FFFFFF', control_pressed='#EBEBEB',
        field='#FFFFFF', log='#FFFFFF', hairline='#E2E2E2', row_sep='#EAEAEA', separator='#DADADA',
        control_border='#C9C9C9', control_border_bottom='#B5B5B5', field_border='#C7C7C7',
        text='#262626', text2='#666666', text3='#A8A8A8', placeholder='#A1A1A1',
        accent='#007AFF', accent_fill='#0064E1', accent_fill_pressed='#0057C4', on_accent='#FFFFFF',
        accent_text='#005CC8', sel_text='#B3D7FF', sel_inactive='#DCDCDC', track='#E2E2E2',
        scroll_handle='rgba(0,0,0,0.26)',
        swatch_edge='#1F000000',
        danger='#C4001A', danger_bg='#FBEAE9', danger_line='#F4B9B5',
        warning='#9C4A00', warning_bg='#FCF1E2', warning_line='#F3D2A2',
        success='#1A7330', success_bg='#E7F5EA', success_line='#B4DFBD',
        info='#005CC8', info_bg='#E8F1FC', info_line='#B7D3F5'),
    'dark': dict(
        page='#232323', sidebar='#2A2A2A', group='#2E2E2E', control='#4A4A4A', control_pressed='#5E5E5E',
        field='#1F1F1F', log='#1B1B1B', hairline='#3D3D3D', row_sep='#383838', separator='#3D3D3D',
        control_border='#565656', control_border_bottom='#565656', field_border='#4A4A4A',
        text='#E4E4E4', text2='#A3A3A3', text3='#666666', placeholder='#767676',
        accent='#0A84FF', accent_fill='#0A5BD1', accent_fill_pressed='#0A50B8', on_accent='#FFFFFF',
        accent_text='#5AA9FF', sel_text='#3F638B', sel_inactive='#464646', track='#3A3A3A',
        scroll_handle='rgba(255,255,255,0.28)',
        swatch_edge='#38FFFFFF',
        danger='#FF7B7E', danger_bg='#3F2726', danger_line='#6E3532',
        warning='#FFA94D', warning_bg='#3D3020', warning_line='#6B5225',
        success='#4CD964', success_bg='#233A27', success_line='#2F6238',
        info='#5AA9FF', info_bg='#1F3043', info_line='#2D4F75'),
}
# Apple macOS text styles in px (Qt on macOS reports 72 dpi, so px equals pt there).
TYPE = dict(title1=(22, 700), title2=(17, 700), title3=(15, 600), headline=(13, 700),
            body=(13, 400), callout=(12, 400), subhead=(11, 400), mono=(11 if sys.platform == 'darwin' else 12, 400))
CONTROL_HEIGHT = 28
SIDEBAR_WIDTH = 220
ASSETS = ROOT / 'src/desktopapp/assets'
_ICON_FOLDER = None  # per-process folder of colour-tinted copies of the SVG assets


def mode(app=None):
    """'dark' or 'light', following the operating system's appearance."""
    app = app or W.QApplication.instance()
    return 'dark' if app is not None and app.styleHints().colorScheme() == QtCore.Qt.ColorScheme.Dark else 'light'


def color(name, scheme=None):
    return COLORS[scheme or mode()][name]


def ui_families():
    """The system UI font first (San Francisco on macOS, Segoe UI on Windows), then the CJK font.
    Only installed families are listed: a missing name costs startup time and can change the result."""
    have = set(QtGui.QFontDatabase.families())
    if sys.platform == 'darwin':
        base, cjk = [QtGui.QFontDatabase.systemFont(QtGui.QFontDatabase.GeneralFont).family()], 'PingFang SC'
    else:
        base, cjk = [f for f in ('Segoe UI Variable Text', 'Segoe UI') if f in have][:1], 'Microsoft YaHei UI'
    return base + ([cjk] if cjk in have else [])


def mono_families():
    have = set(QtGui.QFontDatabase.families())
    wanted = ('Menlo', 'PingFang SC') if sys.platform == 'darwin' else ('Cascadia Mono', 'Consolas', 'Microsoft YaHei UI')
    return [family for family in wanted if family in have] or [QtGui.QFontDatabase.systemFont(QtGui.QFontDatabase.FixedFont).family()]


def tinted(name, colour):
    """Path of an SVG asset with its stroke recoloured, for style sheet url(); one file per colour."""
    global _ICON_FOLDER
    if _ICON_FOLDER is None:
        _ICON_FOLDER = Path(tempfile.mkdtemp(prefix='a7c2-theme-'))
    target = _ICON_FOLDER / ('%s-%s.svg' % (Path(name).stem, colour.lstrip('#').lower()))
    if not target.is_file():
        source = (ASSETS / name).read_text(encoding='utf-8')
        target.write_text(source.replace('#5d6a7e', colour), encoding='utf-8')
    return target.as_posix()


SHEET = Template('''
QWidget {color:$text;}
QMainWindow, QDialog, QMessageBox {background:$page;}
QWidget#content, QScrollArea#page, QScrollArea#page > QWidget > QWidget {background:$page;}
QLabel {background:transparent;}
QLabel[role="title1"] {font-size:22px; font-weight:700;}
QLabel[role="title2"] {font-size:17px; font-weight:700;}
QLabel[role="title3"] {font-size:15px; font-weight:600;}
QLabel[role="headline"] {font-size:13px; font-weight:700;}
QLabel[role="callout"], QLabel[hint="true"] {font-size:12px; color:$text2;}
QLabel[role="subhead"] {font-size:11px; color:$text2;}
QLabel[muted="true"] {color:$text2;}
QLabel[warning="true"] {color:$warning;}
QLabel[danger="true"] {color:$danger;}

QFrame[group="true"], QFrame[card="true"] {background:$group; border:1px solid $hairline; border-radius:8px;}
QFrame[row="true"] {background:transparent; border:0; border-top:1px solid $row_sep; border-radius:0;}
QFrame[row="first"] {background:transparent; border:0;}
QFrame[banner="info"] {background:$info_bg; border:1px solid $info_line; border-radius:8px;}
QFrame[banner="warning"] {background:$warning_bg; border:1px solid $warning_line; border-radius:8px;}
QFrame[banner="danger"] {background:$danger_bg; border:1px solid $danger_line; border-radius:8px;}
QFrame[banner="success"] {background:$success_bg; border:1px solid $success_line; border-radius:8px;}
QLabel[glyph="info"] {color:$info; font-weight:700;}
QLabel[glyph="warning"] {color:$warning; font-weight:700;}
QLabel[glyph="danger"] {color:$danger; font-weight:700;}
QLabel[glyph="success"] {color:$success; font-weight:700;}
QLabel[badge] {font-size:11px; font-weight:600; border-radius:4px; padding:1px 6px;}
QLabel[badge="good"] {color:$success; background:$success_bg; border:1px solid $success_line;}
QLabel[badge="fair"] {color:$info; background:$info_bg; border:1px solid $info_line;}
QLabel[badge="poor"], QLabel[badge="invalid"] {color:$danger; background:$danger_bg; border:1px solid $danger_line;}
QLabel[badge="unknown"] {color:$text2; background:$page; border:1px solid $hairline;}
QLabel#qt_msgbox_label {font-weight:700;}
QLabel[chip="idle"] {color:$text2; font-size:12px;}
QLabel[chip="busy"] {color:$info; font-size:12px; font-weight:600;}

QPushButton {background:$control; color:$text; border:1px solid $control_border; border-bottom-color:$control_border_bottom;
    border-radius:6px; min-height:${control_inner}px; padding:0 12px;}
QPushButton:pressed {background:$control_pressed;}
QPushButton:disabled {color:$text3;}
QPushButton[primary="true"] {background:$accent_fill; color:$on_accent; border:1px solid $accent_fill; font-weight:600;}
QPushButton[primary="true"]:pressed {background:$accent_fill_pressed;}
QPushButton[primary="true"]:disabled {background:$control; color:$text3; border:1px solid $control_border; font-weight:400;}
QPushButton[destructive="true"] {color:$danger; background:$danger_bg; border:1px solid $danger_line;}
QPushButton[quiet="true"] {background:transparent; border:0; color:$accent_text; padding:0 4px; min-height:20px;}
QPushButton[quiet="true"]:pressed {color:$text;}
QPushButton[quiet="true"]:disabled {color:$text3;}
QPushButton:focus {border:1px solid $accent;}
QPushButton[quiet="true"]:focus {border:0; text-decoration:underline;}

QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox {background:$field; color:$text; border:1px solid $field_border;
    border-radius:6px; min-height:${control_inner}px; padding:0 8px; selection-background-color:$sel_text; selection-color:$text;}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus {border:2px solid $accent; padding:0 7px;}
QLineEdit:disabled, QComboBox:disabled, QSpinBox:disabled, QDoubleSpinBox:disabled {color:$text3;}
QLineEdit[readOnly="true"] {background:$page;}
QComboBox {padding-right:24px;}
QComboBox::drop-down {border:0; width:22px;}
QComboBox::down-arrow {image:url("$chevron"); width:10px; height:10px;}
QComboBox QAbstractItemView {background:$group; color:$text; border:1px solid $hairline; outline:0; padding:4px;
    selection-background-color:$accent_fill; selection-color:$on_accent;}
QAbstractSpinBox::up-button, QAbstractSpinBox::down-button {border:0; background:transparent; width:16px;}
QAbstractSpinBox::up-arrow {image:url("$chevron_up"); width:10px; height:10px;}
QAbstractSpinBox::down-arrow {image:url("$chevron"); width:10px; height:10px;}

QCheckBox {spacing:6px; background:transparent;}
QCheckBox::indicator {width:14px; height:14px; border:1px solid $control_border; border-radius:4px; background:$control;}
QCheckBox::indicator:checked {background:$accent; border-color:$accent; image:url("$check");}
QCheckBox::indicator:disabled {background:$page; border-color:$hairline;}
QCheckBox::indicator:checked:disabled {background:$text3; border-color:$text3;}
QCheckBox:disabled {color:$text3;}
QCheckBox:focus {color:$text;}

QToolButton {background:transparent; border:0; color:$text2; padding:2px 0;}
QToolButton:checked, QToolButton:pressed {color:$text;}

QListWidget#sidebar {background:$sidebar; border:0; border-right:1px solid $separator; outline:0; padding:8px 10px;}
QListWidget {background:$group; color:$text; border:1px solid $hairline; border-radius:8px; outline:0;}
QListWidget::item {padding:6px 8px; border-radius:6px;}
QListWidget::item:selected:active {background:$accent_fill; color:$on_accent;}
QListWidget::item:selected:!active {background:$sel_inactive; color:$text;}

QProgressBar {background:$track; border:0; border-radius:3px; max-height:6px; min-height:6px;}
QProgressBar::chunk {background:$accent; border-radius:3px;}
QPlainTextEdit {background:$log; color:$text; border:1px solid $hairline; border-radius:8px; padding:6px;
    selection-background-color:$sel_text;}
QTextBrowser {background:$group; color:$text; border:1px solid $hairline; border-radius:8px; padding:4px;}
QScrollArea {border:0; background:transparent;}
QScrollBar:vertical {background:transparent; width:10px; margin:2px;}
QScrollBar::handle:vertical {background:$scroll_handle; border-radius:3px; min-height:32px;}
QScrollBar:horizontal {background:transparent; height:10px; margin:2px;}
QScrollBar::handle:horizontal {background:$scroll_handle; border-radius:3px; min-width:32px;}
QScrollBar::add-line, QScrollBar::sub-line {width:0; height:0;}
QScrollBar::add-page, QScrollBar::sub-page {background:transparent;}
QToolTip {background:$group; color:$text; border:1px solid $hairline; padding:6px; font-size:12px;}
QMenu {background:$group; color:$text; border:1px solid $hairline; padding:4px;}
QMenu::item {padding:4px 18px; border-radius:4px;}
QMenu::item:selected {background:$accent_fill; color:$on_accent;}
QDialogButtonBox {button-layout:1;}
''')


def stylesheet(scheme):
    tokens = dict(COLORS[scheme], control_inner=CONTROL_HEIGHT - 2,
                  check=(ASSETS / 'check.svg').as_posix(),
                  chevron=tinted('chevron-down.svg', COLORS[scheme]['text2']),
                  chevron_up=tinted('chevron-up.svg', COLORS[scheme]['text2']))
    return SHEET.substitute(tokens)


def palette(scheme):
    tokens, result = COLORS[scheme], QtGui.QPalette()
    roles = dict(Window='page', WindowText='text', Base='field', AlternateBase='group', Text='text',
                 Button='control', ButtonText='text', PlaceholderText='placeholder', Highlight='accent_fill',
                 HighlightedText='on_accent', Link='accent_text', ToolTipBase='group', ToolTipText='text',
                 Accent='accent', Mid='hairline', Midlight='hairline', Dark='separator')
    for role, name in roles.items():
        result.setColor(getattr(QtGui.QPalette.ColorRole, role), QtGui.QColor(tokens[name]))
    disabled = QtGui.QColor(tokens['text3'])
    for role in (QtGui.QPalette.ColorRole.WindowText, QtGui.QPalette.ColorRole.Text, QtGui.QPalette.ColorRole.ButtonText):
        result.setColor(QtGui.QPalette.ColorGroup.Disabled, role, disabled)
    return result


def apply(app):
    """Style the whole application for the current appearance; returns 'light' or 'dark'.
    Does nothing when that appearance is already applied: re-setting an application style sheet
    restyles every existing widget, which grows with each window opened."""
    scheme, previous = mode(app), app.property('a7c2_theme')
    if previous == scheme:
        return scheme
    app.setProperty('a7c2_theme', scheme)
    if previous is None:
        # Fusion is predictable under style sheets on every platform. Set it only once: with a
        # style sheet applied, app.style() is Qt's style sheet wrapper and no longer says 'fusion'.
        app.setStyle('Fusion')
    font = QtGui.QFont()
    font.setFamilies(ui_families())
    font.setPixelSize(TYPE['body'][0])
    app.setFont(font)
    app.setPalette(palette(scheme))
    app.setStyleSheet(stylesheet(scheme))
    return scheme


def mono_font():
    font = QtGui.QFont()
    font.setFamilies(mono_families())
    font.setPixelSize(TYPE['mono'][0])
    return font


def repolish(widget):
    """Apply a changed dynamic property (role, kind, banner…) to an already styled widget."""
    widget.style().unpolish(widget)
    widget.style().polish(widget)
    widget.update()
