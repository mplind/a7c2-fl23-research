"""Film look library and offline preview dialogs. This module never opens a camera."""
import html
from pathlib import Path
import shutil
import tempfile
import threading
import numpy as np
from PySide6 import QtCore, QtGui, QtWidgets as W
from .engine_text import display  # engine errors, shown in English when the interface is English
from .i18n import tr
from . import theme


def rating_word(rating):
    return {'good': tr('良好'), 'fair': tr('一般'), 'poor': tr('较差'), 'unknown': tr('未知'), 'invalid': tr('无法读取')}[rating]


def kind_word(kind):
    return {'negative': tr('彩色负片'), 'slide': tr('反转片'), 'cine': tr('电影胶片'), 'style': tr('风格外观')}[kind]


def fit_text(fit):
    if fit['rating'] == 'invalid':
        return tr('无法读取此 A7Look：') + display(fit['error'])
    if fit['rating'] == 'unknown':
        return tr('拟合：未知（文件没有留出验证数据）')
    text = tr('拟合：%s（MAE %.1f · P95 %.1f）') % (rating_word(fit['rating']), fit['mae'], fit['p95'])
    return text + (tr('；机内效果会明显偏离原外观') if fit['rating'] == 'poor' else '')


def fit_help():
    return tr('MAE／P95：留出颜色上的 8 位 RGB 误差。良好＝不差于内置配对库的中位数；一般＝不差于其中最差的已收录外观；较差＝超出该范围。')


def colour_note(colour):
    """How the photo's colours were handled, as a sentence to append to the status (or '')."""
    if colour is None:
        return ''
    if colour['kind'] == 'converted':
        return ' ' + tr('照片已从 %s 转换为 sRGB。') % colour['profile']
    return ' ' + tr('照片标记为非 sRGB（可能是 Adobe RGB）但没有内嵌配置文件，已按 sRGB 处理，颜色会有偏差。')


LOOK = QtCore.Qt.UserRole
SWATCH, GAP = 10, 2  # a list row's swatches and the gap between them, px


def swatch_centres(rect, count, size=SWATCH, gap=GAP):
    """Centre points of count swatches laid left to right from rect's top-left."""
    return [QtCore.QPoint(rect.left() + i * (size + gap) + size // 2, rect.top() + size // 2) for i in range(count)]


def paint_swatches(painter, rect, colours, size=SWATCH, gap=GAP, radius=2):
    """Rounded squares left to right from rect's top-left, each with a faint edge so a near-black
    swatch still shows on a dark window and a pale one on a light window."""
    painter.save()
    painter.setRenderHint(QtGui.QPainter.Antialiasing)
    painter.setPen(QtGui.QPen(QtGui.QColor(theme.color('swatch_edge')), 1))
    for i, colour in enumerate(colours):
        painter.setBrush(QtGui.QColor(colour))
        box = QtCore.QRectF(rect.left() + i * (size + gap), rect.top(), size, size).adjusted(0.5, 0.5, -0.5, -0.5)
        painter.drawRoundedRect(box, radius, radius)
    painter.restore()


def fit_colour(rating):
    return theme.color({'good': 'success', 'fair': 'info', 'unknown': 'text2'}.get(rating, 'danger'))


def look_summary(look):
    return '%s, %s, %s' % (look['name'], kind_word(look['kind']), tr('拟合：') + rating_word(look['fit']['rating']))


class LookDelegate(W.QStyledItemDelegate):
    """Library rows: the look's name over its kind, and its swatch strip over its fit, trailing."""
    ROW = 46

    def sizeHint(self, option, index):
        return QtCore.QSize(option.rect.width(), self.ROW)

    def strip_rect(self, rect):
        from .looklibrary import REFERENCE
        width = len(REFERENCE) * (SWATCH + GAP) - GAP
        return QtCore.QRect(rect.right() - 10 - width + 1, rect.top() + 10, width, SWATCH)

    def paint(self, painter, option, index):
        look = index.data(LOOK)
        painter.save()
        painter.setRenderHint(QtGui.QPainter.Antialiasing)
        rect = QtCore.QRect(option.rect)
        selected = bool(option.state & W.QStyle.State_Selected)
        on_accent = selected and bool(option.state & W.QStyle.State_Active)
        if selected:
            painter.setPen(QtCore.Qt.NoPen)
            painter.setBrush(QtGui.QColor(theme.color('accent_fill' if on_accent else 'sel_inactive')))
            painter.drawRoundedRect(QtCore.QRectF(rect).adjusted(2, 1, -2, -1), 6, 6)
        strip = self.strip_rect(rect)
        if look.get('swatches'):
            paint_swatches(painter, strip, look['swatches'])
        words = rect.adjusted(10, 0, -(rect.right() - strip.left() + 12), 0)
        name, detail = QtGui.QFont(option.font), QtGui.QFont(option.font)
        name.setPixelSize(13); name.setWeight(QtGui.QFont.Medium); detail.setPixelSize(11)
        painter.setFont(name)
        painter.setPen(QtGui.QColor(theme.color('on_accent' if on_accent else 'text')))
        painter.drawText(QtCore.QRect(words.left(), rect.top() + 6, words.width(), 18), QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter,
                         QtGui.QFontMetrics(name).elidedText(look['name'], QtCore.Qt.ElideRight, words.width()))
        painter.setFont(detail)
        painter.setPen(QtGui.QColor(theme.color('on_accent' if on_accent else 'text2')))
        painter.drawText(QtCore.QRect(words.left(), rect.top() + 24, words.width(), 16), QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter,
                         kind_word(look['kind']))
        painter.setPen(QtGui.QColor(theme.color('on_accent') if on_accent else fit_colour(look['fit']['rating'])))
        painter.drawText(QtCore.QRect(strip.left(), rect.top() + 24, strip.width(), 16), QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter,
                         tr('拟合：') + rating_word(look['fit']['rating']))
        painter.restore()


class SwatchStrip(W.QWidget):
    """The reference colours over the selected look's predicted in-camera rendering of them."""
    SIZE, SPACE = 22, 4

    def __init__(self):
        super().__init__()
        from .looklibrary import REFERENCE
        self.references = ['#%02X%02X%02X' % rgb for _, rgb in REFERENCE]
        self.colours = []
        self.rows = (tr('参考色'), tr('机内'))
        self.setFixedHeight(2 * self.SIZE + self.SPACE)
        self.setToolTip(tr('上：参考色（%s）。下：此外观在相机中的预测效果。') % tr('、').join(tr(name) for name, _ in REFERENCE))

    def show_look(self, colours):
        self.colours = list(colours or [])
        self.setVisible(bool(self.colours))
        self.update()

    def label_width(self):
        font = QtGui.QFont(self.font()); font.setPixelSize(11)
        return max(QtGui.QFontMetrics(font).horizontalAdvance(row) for row in self.rows) + 10

    def paintEvent(self, event):
        painter = QtGui.QPainter(self)
        font = QtGui.QFont(self.font()); font.setPixelSize(11)
        painter.setFont(font)
        painter.setPen(QtGui.QColor(theme.color('text2')))
        left = self.label_width()
        for row, (label, colours) in enumerate(zip(self.rows, (self.references, self.colours))):
            top = row * (self.SIZE + self.SPACE)
            painter.drawText(QtCore.QRect(0, top, left, self.SIZE), QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter, label)
            paint_swatches(painter, QtCore.QRect(left, top, 0, 0), colours, self.SIZE, self.SPACE, 4)
        painter.end()


class FilmLibraryDialog(W.QDialog):
    add_requested = QtCore.Signal(object, int)
    preview_requested = QtCore.Signal(str)

    def __init__(self, looks, parent=None, *, notices=None):
        super().__init__(parent)
        self.looks = looks
        self.setWindowTitle(tr('胶片外观库'))
        self.resize(900, 600)
        box = W.QVBoxLayout(self)
        box.setContentsMargins(20, 20, 20, 20); box.setSpacing(12)
        intro = W.QLabel(tr('每款外观都注明来源、许可和机内拟合。先用自己的照片预览，再添加到清单中的自订槽位。'))
        intro.setWordWrap(True); intro.setProperty('role', 'callout'); box.addWidget(intro)
        middle = W.QHBoxLayout(); middle.setSpacing(16); box.addLayout(middle, 1)
        self.list = W.QListWidget(); self.list.setFixedWidth(330)
        self.list.setItemDelegate(LookDelegate(self.list))
        for look in looks:
            item = W.QListWidgetItem(look['name'])
            item.setData(LOOK, look)
            item.setToolTip(look_summary(look))
            item.setData(QtCore.Qt.AccessibleTextRole, look_summary(look))
            self.list.addItem(item)
        middle.addWidget(self.list)
        right = W.QVBoxLayout(); right.setSpacing(10); middle.addLayout(right, 1)
        self.strip = SwatchStrip()
        right.addWidget(self.strip)
        self.details = W.QTextBrowser(); self.details.setOpenExternalLinks(True)
        right.addWidget(self.details, 1)
        choose = W.QHBoxLayout(); choose.setSpacing(8); right.addLayout(choose)
        slot_label = W.QLabel(tr('目标槽位')); slot_label.setProperty('muted', True); choose.addWidget(slot_label)
        self.slot = W.QComboBox()
        for number in range(1, 7):
            self.slot.addItem(tr('自订 %d') % number, number)
        choose.addWidget(self.slot); choose.addStretch()
        self.preview = W.QPushButton(tr('在我的照片上预览…'))
        choose.addWidget(self.preview)
        # Apple order: supporting action leading; Close, then the primary action, trailing.
        actions = W.QHBoxLayout(); actions.setSpacing(8); box.addLayout(actions)
        if notices is not None:
            licences = W.QPushButton(tr('许可声明…'))
            licences.clicked.connect(lambda: QtGui.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(str(notices))))
            actions.addWidget(licences)
        actions.addStretch()
        close = W.QPushButton(tr('关闭')); close.clicked.connect(self.accept); actions.addWidget(close)
        self.add = W.QPushButton(tr('添加到清单')); self.add.setProperty('primary', True)
        actions.addWidget(self.add)
        # Bound methods, not lambdas: a lambda capturing self keeps a closed dialog alive.
        self.add.clicked.connect(self.request_add)
        self.preview.clicked.connect(self.request_preview)
        self.list.currentRowChanged.connect(self.show_details)
        self.list.setCurrentRow(0)

    def selected(self):
        return self.looks[self.list.currentRow()]

    def request_add(self):
        self.add_requested.emit(self.selected(), self.slot.currentData())

    def request_preview(self):
        self.preview_requested.emit(str(self.selected()['path']))

    def restyle(self):
        self.show_details(self.list.currentRow())
        self.list.viewport().update()

    def show_details(self, row):
        look = self.looks[row]; source = look['source']; fit = look['fit']
        self.preview.setEnabled(look['preview'])
        self.strip.show_look(look.get('swatches'))
        rows = [(tr('来源'), tr('%s，作者 %s') % (html.escape(source['project']), html.escape(source['author']))),
                (tr('网址'), '<a href="%s">%s</a>' % (html.escape(source['url'], quote=True), html.escape(source['url']))),
                (tr('许可'), html.escape(source['licence'])),
                (tr('改动'), html.escape(look['modification'])),
                (tr('可否分享'), tr('可以，按上述许可') if look['shareable'] else tr('仅限个人使用'))]
        if look['notes']:
            rows.append((tr('注意'), html.escape(look['notes'])))
        table = ''.join('<tr><td style="padding:3px 12px 3px 0;color:%s">%s</td><td style="padding:3px 0">%s</td></tr>'
                        % (theme.color('text2'), html.escape(key), value) for key, value in rows)
        from .looklibrary import CONCERNS
        colour = theme.color('warning') if fit['rating'] in CONCERNS else theme.color('text')
        self.details.setHtml('<h3>%s</h3><p style="color:%s">%s</p><table>%s</table><p style="color:%s">%s</p>'
                             % (html.escape(look['name']), colour, html.escape(fit_text(fit)), table,
                                theme.color('text2'), html.escape(fit_help())))


class Panel(W.QWidget):
    def __init__(self, caption):
        super().__init__()
        box = W.QVBoxLayout(self); box.setContentsMargins(0, 0, 0, 0)
        self.pixmap = None
        self.image = W.QLabel(); self.image.setAlignment(QtCore.Qt.AlignCenter); self.image.setMinimumSize(260, 180)
        # The pixmap follows the panel size; it must not drive the layout itself.
        self.image.setSizePolicy(W.QSizePolicy.Ignored, W.QSizePolicy.Ignored)
        self.caption = W.QLabel(caption); self.caption.setAlignment(QtCore.Qt.AlignCenter); self.caption.setWordWrap(True)
        box.addWidget(self.image, 1); box.addWidget(self.caption)

    def show_pixels(self, pixels):
        pixels = np.ascontiguousarray(pixels)
        height, width = pixels.shape[:2]
        image = QtGui.QImage(pixels.data, width, height, 3 * width, QtGui.QImage.Format_RGB888).copy()
        self.pixmap = QtGui.QPixmap.fromImage(image)
        self.fit()

    def fit(self):
        if self.pixmap is not None:
            size = self.image.size().expandedTo(self.image.minimumSize())
            self.image.setPixmap(self.pixmap.scaled(size, QtCore.Qt.KeepAspectRatio, QtCore.Qt.SmoothTransformation))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.fit()


class RenderJob:
    """One preview render on a daemon thread. It holds no Qt object: a dialog closed mid-render
    is released on the GUI thread, and the render finishes on its own with its result dropped."""

    def __init__(self, render, document, photo, output, cache):
        self.result = None
        self.thread = threading.Thread(target=self.run, args=(render, document, photo, output, cache),
                                       name='a7c2-preview', daemon=True)
        self.thread.start()

    def run(self, render, document, photo, output, cache):
        try:
            self.result = ('done', render(document, photo, output, cache=cache))
        except Exception as exc:  # reported in the dialog; the GUI must survive any render failure
            self.result = ('failed', exc)

    def done(self):
        return not self.thread.is_alive()


class PreviewDialog(W.QDialog):
    """Renders through a RenderJob; the model work cannot be cancelled, so a closed dialog just drops the result."""

    def __init__(self, look, *, cache, parent=None, render=None):
        super().__init__(parent)
        from looktool import lookfile
        self.document = lookfile.read(look)
        self.cache = Path(cache)
        self.render = render
        self.workspace = tempfile.TemporaryDirectory(prefix='a7c2-preview-')
        self.output = Path(self.workspace.name) / 'preview.png'
        self.job = None
        self.setWindowTitle(tr('预览：') + self.document['name'])
        self.resize(980, 520)
        box = W.QVBoxLayout(self)
        hint = W.QLabel(tr('请选用以创意外观 ST 拍摄的 JPEG：预览把外观套在这张 ST 照片上，与相机的做法一致。机内预测来自拟合模型，不是实拍。'))
        hint.setWordWrap(True); box.addWidget(hint)
        top = W.QHBoxLayout(); box.addLayout(top)
        self.choose = W.QPushButton(tr('选择照片…')); self.choose.clicked.connect(self.choose_photo); top.addWidget(self.choose)
        self.progress = W.QProgressBar(); self.progress.setRange(0, 0); self.progress.setFixedWidth(160); self.progress.hide()
        top.addWidget(self.progress)
        self.status = W.QLabel(tr('尚未选择照片')); self.status.setWordWrap(True); top.addWidget(self.status, 1)
        row = W.QHBoxLayout(); box.addLayout(row, 1)
        self.panels = {'photo': Panel(tr('你的照片（ST）')), 'source': Panel(tr('原外观（直接套用 LUT）')),
                       'camera': Panel(tr('机内预测（拟合模型）'))}
        for panel in self.panels.values():
            panel.hide(); row.addWidget(panel, 1)
        bottom = W.QHBoxLayout(); box.addLayout(bottom)
        self.save = W.QPushButton(tr('保存对比图…')); self.save.setEnabled(False); self.save.clicked.connect(self.save_image)
        close = W.QPushButton(tr('关闭')); close.clicked.connect(self.accept)
        bottom.addWidget(self.save); bottom.addStretch(); bottom.addWidget(close)
        self.timer = QtCore.QTimer(self); self.timer.setInterval(100); self.timer.timeout.connect(self.poll)

    def busy(self):
        return self.job is not None

    def choose_photo(self):
        path = W.QFileDialog.getOpenFileName(self, tr('选择照片'), '', tr('照片 (*.jpg *.jpeg *.png *.tif *.tiff)'))[0]
        if path:
            self.start(Path(path))

    def start(self, photo):
        if self.busy():
            return
        render = self.render
        if render is None:
            from looktool import lookpreview
            render = lookpreview.render
        self.choose.setEnabled(False); self.save.setEnabled(False); self.progress.show()
        self.status.setText(tr('正在生成预览……每款外观首次预览约需一分钟，之后很快。'))
        self.job = RenderJob(render, self.document, photo, self.output, self.cache)
        self.timer.start()

    def poll(self):
        if self.job is None or not self.job.done():
            return
        outcome, value = self.job.result
        self.timer.stop(); self.job = None
        self.progress.hide(); self.choose.setEnabled(True)
        if outcome == 'failed':
            self.status.setText(tr('预览失败：') + display(str(value)))
            return
        panels = {panel['role']: panel for panel in value['panels']}
        for role, panel in self.panels.items():
            panel.setVisible(role in panels)
            if role in panels:
                panel.show_pixels(panels[role]['pixels'])
        if 'source' in panels:
            self.panels['source'].caption.setText(
                tr('原外观（DCP）') if panels['source'].get('kind') == 'dcp' else tr('原外观（直接套用 LUT）'))
        text = tr('预览完成。') if 'source' in panels else tr('预览完成。此外观没有内嵌原始 LUT，只显示机内预测。')
        self.status.setText(text + colour_note(value.get('colour')))
        self.save.setEnabled(True)

    def save_image(self):
        path = W.QFileDialog.getSaveFileName(self, tr('保存对比图'), 'preview.png', 'PNG (*.png)')[0]
        if not path:
            return
        try:
            shutil.copyfile(self.output, path)
        except OSError as exc:
            W.QMessageBox.warning(self, tr('保存失败'), display(str(exc)))
