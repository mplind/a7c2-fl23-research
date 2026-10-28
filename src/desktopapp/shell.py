"""Window chrome in the Apple style: sidebar sections, Settings-style groups and rows, the status
area with its log, the Settings window and camera-write confirmations. Never opens a camera."""
from PySide6 import QtCore, QtGui, QtSvg, QtWidgets as W
from . import theme
from .engine_text import display
from .i18n import tr

# 16 px line icons, 1.5 px strokes, in the spirit of SF Symbols (which Qt cannot load).
ICONS = {
    'home': '<path d="M2.6 7.4 8 3l5.4 4.4V13a.6.6 0 0 1-.6.6H9.7V10.2H6.3v3.4H3.2a.6.6 0 0 1-.6-.6Z"/>',
    'connection': '<path d="M5.6 2.4v3M10.4 2.4v3M4.2 5.4h7.6v2.2a3.8 3.8 0 0 1-7.6 0ZM8 11.4v2.6"/>',
    'restore': '<path d="M3.2 8a4.8 4.8 0 1 0 1.4-3.4M3 2.6v2.8h2.8"/>',
    'film': '<path d="M3 2.8h10v10.4H3ZM5.6 2.8v10.4M10.4 2.8v10.4M3 6.2h2.6M3 9.8h2.6M10.4 6.2H13M10.4 9.8H13"/>',
    'looks': '<circle cx="6" cy="6.2" r="3.2"/><circle cx="10" cy="6.2" r="3.2"/><circle cx="8" cy="9.8" r="3.2"/>',
    'vertical': '<path d="M5.2 2.4h5.6a.8.8 0 0 1 .8.8v9.6a.8.8 0 0 1-.8.8H5.2a.8.8 0 0 1-.8-.8V3.2a.8.8 0 0 1 .8-.8ZM7 11.6h2"/>',
    'sound': '<path d="M2.8 6.2h2.4l3.2-2.6v8.8L5.2 9.8H2.8ZM10.8 5.8a3.2 3.2 0 0 1 0 4.4M12.6 4.1a5.6 5.6 0 0 1 0 7.8"/>',
    'recipes': '<path d="M6.2 2.6h3.6M6.8 2.6v3.8L3.4 12.2a.8.8 0 0 0 .7 1.2h7.8a.8.8 0 0 0 .7-1.2L9.2 6.4V2.6M5 10h6"/>',
    'info': '<circle cx="8" cy="8" r="6.2"/><path d="M8 7.2v4M8 4.9v.1"/>',
    'warning': '<path d="M8 2.4 14 13H2ZM8 6.4v3.4M8 11.4v.1"/>',
    'danger': '<circle cx="8" cy="8" r="6.2"/><path d="M5.8 5.8l4.4 4.4M10.2 5.8l-4.4 4.4"/>',
    'success': '<circle cx="8" cy="8" r="6.2"/><path d="M5.2 8.2l1.9 1.9 3.8-3.8"/>',
}


def icon_pixmap(name, colour, size=16, ratio=2.0):
    """A crisp tinted icon at the device pixel ratio."""
    svg = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16" fill="none" stroke="%s" '
           'stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">%s</svg>' % (colour, ICONS[name]))
    renderer = QtSvg.QSvgRenderer(QtCore.QByteArray(svg.encode()))
    pixmap = QtGui.QPixmap(int(size * ratio), int(size * ratio))
    pixmap.fill(QtCore.Qt.transparent)
    painter = QtGui.QPainter(pixmap)
    renderer.render(painter)
    painter.end()
    pixmap.setDevicePixelRatio(ratio)
    return pixmap


def modal(dialog):
    """Run a dialog to completion, then release it. A dialog parented to the window is owned by
    it, so without this every opening would leave a hidden dialog behind. Returns exec()'s result;
    the dialog stays readable until control returns to the event loop."""
    try:
        return dialog.exec()
    finally:
        dialog.deleteLater()


def warn(parent, title, exc):
    """An alert titled `title` showing the error `exc` raised; engine text in the interface language."""
    W.QMessageBox.warning(parent, title, display(str(exc)))


def ask(parent, title, text, verb, *, details=None):
    """A camera-write confirmation: a window-modal sheet with Cancel and a verb button. Cancel is the
    default button, so Return cannot confirm a write by reflex, and Escape cancels too. True for
    the verb."""
    box = W.QMessageBox(parent)
    box.setIcon(W.QMessageBox.Warning)
    box.setWindowTitle(title)
    box.setText(title)
    box.setInformativeText(text)
    if details:
        box.setDetailedText(details)
    go = box.addButton(verb, W.QMessageBox.AcceptRole)
    go.setAutoDefault(False)  # shown, a dialog makes its first auto-default button the default
    cancel = box.addButton(W.QMessageBox.Cancel)
    box.setDefaultButton(cancel)
    box.setEscapeButton(cancel)
    box.setWindowModality(QtCore.Qt.WindowModal)
    modal(box)
    return box.clickedButton() is go


# ---------------------------------------------------------------- sidebar
SECTION, ICON = QtCore.Qt.UserRole, QtCore.Qt.UserRole + 1
ROW, HEADER = 28, 26


class SidebarDelegate(W.QStyledItemDelegate):
    """macOS source-list rows: 28 px, inset rounded selection, a tinted icon, and a section title
    drawn above the first row of each section (rows stay one-to-one with pages)."""

    def sizeHint(self, option, index):
        return QtCore.QSize(option.rect.width(), ROW + (HEADER if index.data(SECTION) else 0))

    def paint(self, painter, option, index):
        painter.save()
        painter.setRenderHint(QtGui.QPainter.Antialiasing)
        rect = QtCore.QRect(option.rect)
        section = index.data(SECTION)
        if section:
            header = QtCore.QRect(rect.left() + 8, rect.top(), rect.width() - 8, HEADER)
            font = QtGui.QFont(option.font); font.setPixelSize(11); font.setWeight(QtGui.QFont.DemiBold)
            painter.setFont(font)
            painter.setPen(QtGui.QColor(theme.color('text2')))
            painter.drawText(header.adjusted(0, 0, 0, -5), QtCore.Qt.AlignLeft | QtCore.Qt.AlignBottom, section)
            rect.setTop(rect.top() + HEADER)
        selected = bool(option.state & W.QStyle.State_Selected)
        active = bool(option.state & W.QStyle.State_Active)
        if selected:
            painter.setPen(QtCore.Qt.NoPen)
            painter.setBrush(QtGui.QColor(theme.color('accent_fill' if active else 'sel_inactive')))
            painter.drawRoundedRect(QtCore.QRectF(rect).adjusted(0, 1, 0, -1), 6, 6)
        on_accent = selected and active
        icon = index.data(ICON)
        if icon:
            colour = theme.color('on_accent' if on_accent else 'accent')
            painter.drawPixmap(rect.left() + 8, rect.top() + (rect.height() - 16) // 2,
                               icon_pixmap(icon, colour, ratio=painter.device().devicePixelRatioF() or 2.0))
        font = QtGui.QFont(option.font); font.setPixelSize(13)
        painter.setFont(font)
        painter.setPen(QtGui.QColor(theme.color('on_accent' if on_accent else 'text')))
        text_rect = rect.adjusted(32, 0, -6, 0)
        text = QtGui.QFontMetrics(font).elidedText(index.data(QtCore.Qt.DisplayRole), QtCore.Qt.ElideRight, text_rect.width())
        painter.drawText(text_rect, QtCore.Qt.AlignVCenter | QtCore.Qt.AlignLeft, text)
        painter.restore()


def sidebar(entries):
    """A source list from (section or None, label, icon) entries; full labels in tooltips."""
    nav = W.QListWidget()
    nav.setObjectName('sidebar')
    nav.setFixedWidth(theme.SIDEBAR_WIDTH)
    nav.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
    nav.setItemDelegate(SidebarDelegate(nav))
    nav.setMouseTracking(False)
    for section, label, icon in entries:
        item = W.QListWidgetItem(label)
        item.setData(SECTION, section)
        item.setData(ICON, icon)
        item.setToolTip(label)
        item.setData(QtCore.Qt.AccessibleTextRole, label)
        nav.addItem(item)
    return nav


# ---------------------------------------------------------------- page building blocks
def text_label(text, role=None, *, wrap=True, selectable=False):
    label = W.QLabel(text)
    if role:
        label.setProperty('role', role)
    label.setWordWrap(wrap)
    if selectable:
        label.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
    return label


class Group(W.QFrame):
    """A Settings-style group: rows separated by hairlines inside one rounded box."""

    def __init__(self):
        super().__init__()
        self.setProperty('group', True)
        self.rows = W.QVBoxLayout(self)
        self.rows.setContentsMargins(12, 2, 12, 2)
        self.rows.setSpacing(0)

    def add(self, widget):
        """Add a row widget; every row after the first gets a hairline above it."""
        frame = W.QFrame()
        frame.setProperty('row', 'first' if self.rows.count() == 0 else True)
        box = W.QVBoxLayout(frame)
        box.setContentsMargins(0, 9, 0, 9)
        box.addWidget(widget)
        self.rows.addWidget(frame)
        return widget


class ActionRow(W.QWidget):
    """Title and help on the leading side, controls on the trailing side. help_text may be a
    label the caller keeps updating (a live status line)."""

    def __init__(self, title, help_text='', controls=()):
        super().__init__()
        line = W.QHBoxLayout(self)
        line.setContentsMargins(0, 0, 0, 0)
        line.setSpacing(12)
        words = W.QVBoxLayout()
        words.setSpacing(2)
        self.title = text_label(title)
        words.addWidget(self.title)
        self.help = help_text if isinstance(help_text, W.QLabel) else text_label(help_text, 'callout')
        self.help.setProperty('role', 'callout')
        self.help.setWordWrap(True)
        self.help.setVisible(bool(self.help.text()))
        words.addWidget(self.help)
        line.addLayout(words, 1)
        self.controls = W.QHBoxLayout()
        self.controls.setSpacing(8)
        line.addLayout(self.controls)
        for control in controls:
            self.controls.addWidget(control, 0, QtCore.Qt.AlignVCenter)


class CheckRow(W.QWidget):
    """A checkbox with its help text underneath, aligned with the checkbox label."""

    def __init__(self, checkbox, help_text=''):
        super().__init__()
        box = W.QVBoxLayout(self)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(2)
        box.addWidget(checkbox)
        self.help = help_text if isinstance(help_text, W.QLabel) else text_label(help_text, 'callout')
        self.help.setProperty('role', 'callout')
        self.help.setWordWrap(True)
        self.help.setContentsMargins(20, 0, 0, 0)
        self.help.setVisible(bool(self.help.text()))
        box.addWidget(self.help)


def section(layout, title):
    """A headline above a new group; returns the group."""
    if title:
        heading = text_label(title, 'headline')
        heading.setContentsMargins(2, 6, 0, 0)
        layout.addWidget(heading)
    group = Group()
    layout.addWidget(group)
    return group


class Banner(W.QFrame):
    """Persistent status in colour, glyph and words; kind is '' (plain text), info, warning,
    danger or success."""

    def __init__(self):
        super().__init__()
        line = W.QHBoxLayout(self)
        line.setContentsMargins(12, 10, 12, 10)
        line.setSpacing(10)
        self.glyph = W.QLabel()
        self.glyph.setFixedSize(16, 16)
        line.addWidget(self.glyph, 0, QtCore.Qt.AlignTop)
        words = W.QVBoxLayout()
        words.setSpacing(8)
        self.text = text_label('', selectable=True)
        words.addWidget(self.text)
        self.progress = W.QProgressBar()
        self.progress.setTextVisible(False)
        self.progress.hide()
        words.addWidget(self.progress)
        line.addLayout(words, 1)
        self.actions = W.QHBoxLayout()
        self.actions.setSpacing(8)
        line.addLayout(self.actions)
        self.kind = None
        self.set_kind('')

    def set_kind(self, kind):
        if kind == self.kind:
            return
        self.kind = kind
        self.setProperty('banner', kind or None)
        self.glyph.setVisible(bool(kind))
        self.layout().setContentsMargins(*((12, 10, 12, 10) if kind else (2, 0, 2, 0)))
        self.text.setProperty('role', None if kind else 'callout')
        self.refresh()

    def refresh(self):
        """Re-tint the glyph and restyle (also after the appearance changes)."""
        if self.kind:
            self.glyph.setPixmap(icon_pixmap(self.kind, theme.color(self.kind)))
        theme.repolish(self)
        theme.repolish(self.text)


class StatusArea(W.QWidget):
    """Under the page title: the status banner with its progress bar and Stop button, then the
    Show Log disclosure with the task folder and diagnostics actions, then the log itself."""

    def __init__(self):
        super().__init__()
        box = W.QVBoxLayout(self)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(6)
        self.banner = Banner()
        box.addWidget(self.banner)
        self.stop = W.QPushButton(tr('停止离线任务'))
        self.stop.setEnabled(False)
        self.stop.hide()
        self.banner.actions.addWidget(self.stop, 0, QtCore.Qt.AlignTop)
        tools = W.QHBoxLayout()
        tools.setSpacing(12)
        self.toggle = W.QToolButton()
        self.toggle.setCheckable(True)
        self.toggle.setToolButtonStyle(QtCore.Qt.ToolButtonTextBesideIcon)
        self.toggle.setArrowType(QtCore.Qt.RightArrow)
        self.toggle.setText(tr('显示日志'))
        self.toggle.toggled.connect(self.show_log)
        tools.addWidget(self.toggle)
        tools.addStretch()
        self.open_folder = W.QPushButton(tr('打开任务目录'))
        self.export = W.QPushButton(tr('导出诊断包'))
        for button in (self.open_folder, self.export):
            button.setProperty('quiet', True)
            tools.addWidget(button)
        box.addLayout(tools)
        self.log = W.QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setFont(theme.mono_font())
        self.log.setLineWrapMode(W.QPlainTextEdit.WidgetWidth)  # instructions read without scrolling sideways
        self.log.setMinimumHeight(150)
        self.log.setMaximumHeight(220)
        self.log.setPlaceholderText(tr('完整运行日志与原始报错会显示在这里。'))
        self.log.hide()
        box.addWidget(self.log)

    def show_log(self, shown):
        self.log.setVisible(shown)
        self.toggle.setArrowType(QtCore.Qt.DownArrow if shown else QtCore.Qt.RightArrow)
        self.toggle.setText(tr('隐藏日志') if shown else tr('显示日志'))
        if self.toggle.isChecked() != shown:
            self.toggle.setChecked(shown)


class SettingsDialog(W.QDialog):
    """App settings (⌘, on macOS): the interface language, the supported camera firmware and the
    app version (for bug reports)."""

    def __init__(self, parent, language_combo, firmware, version):
        super().__init__(parent)
        self.setWindowTitle(tr('设置'))
        self.setMinimumWidth(460)
        box = W.QVBoxLayout(self)
        box.setContentsMargins(20, 20, 20, 20)
        box.setSpacing(8)
        group = section(box, tr('通用'))
        group.add(ActionRow(tr('界面语言'), tr('下次打开 A7C II Tools 时生效。当前输入和任务保持不变。'), [language_combo]))
        group.add(ActionRow(tr('相机固件'), tr('本版本只支持 ILCE-7CM2 固件 2.01。'), [text_label(firmware, wrap=False)]))
        group.add(ActionRow(tr('版本'), tr('报告问题时请附上版本号和诊断包。'), [text_label(version, wrap=False, selectable=True)]))
        buttons = W.QDialogButtonBox(W.QDialogButtonBox.Close)
        buttons.rejected.connect(self.reject)
        buttons.accepted.connect(self.accept)
        box.addStretch()
        box.addWidget(buttons)
