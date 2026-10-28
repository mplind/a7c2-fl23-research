"""Shared helpers for the desktop GUI tests; no camera access."""
import re
from unittest.mock import Mock
from desktopapp import jobs
from desktopapp.engine_text import CJK  # noqa: F401  every CJK character Task 8b names, shared with the translator
from desktopapp.paths import write_json

# Han characters and full-width punctuation: none may appear in the English interface.
HAN = re.compile('[㐀-鿿（），：；、。“”]')


def stopped_banner(english):
    """The English banner for a job that stopped with the error `english` (window.joined keeps one full stop)."""
    return 'Stopped: ' + english.rstrip('.') + '. Export diagnostics to report it.'


def shown_texts(widget):
    """Every string `widget` and its children show: window and group titles, labels, buttons, field
    texts and placeholders, list and menu items, text views, message box texts and tooltips."""
    from PySide6 import QtWidgets as W
    texts = [widget.windowTitle()]
    if isinstance(widget, W.QMessageBox):
        texts += [widget.text(), widget.informativeText(), widget.detailedText()]
    for child in [widget] + widget.findChildren(W.QWidget):
        if isinstance(child, (W.QLabel, W.QAbstractButton)):
            texts.append(child.text())
        if isinstance(child, W.QGroupBox):
            texts.append(child.title())
        if isinstance(child, W.QLineEdit):
            texts += [child.text(), child.placeholderText()]
        if isinstance(child, (W.QTextEdit, W.QPlainTextEdit)):
            texts += [child.toPlainText(), child.placeholderText()]
        if isinstance(child, W.QComboBox):
            texts += [child.itemText(index) for index in range(child.count())]
        if isinstance(child, W.QListWidget):
            texts += [child.item(row).text() for row in range(child.count())]
        texts.append(child.toolTip())
    return [text for text in texts if text]


def finish_job(window, action, result=None, error=None):
    """Let window.finished() handle a worker job that succeeded with result or failed with error."""
    window.current_job = jobs.new_job(action, {})
    status = dict(phase='SUCCEEDED', action=action, result=result) if error is None else \
        dict(phase='FAILED', action=action, error=error)
    write_json(window.current_job / 'status.private.json', status)
    window.process = Mock()
    window.finished(0 if error is None else 2, None)
