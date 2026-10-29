"""Shared helpers for the desktop GUI tests; no camera access."""
import importlib.util
from pathlib import Path
import re
from unittest.mock import Mock
from desktopapp import jobs
from desktopapp.paths import write_json

# Han characters and the common full-width punctuation: none may appear in the English interface. Not
# engine_text.HAN (the ideographs alone) nor engine_text.CJK (every CJK block), hence the longer name.
HAN_OR_PUNCTUATION = re.compile('[㐀-鿿（），：；、。“”]')


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


def finish_job(window, action, result=None, error=None, error_type=None):
    """Let window.finished() handle a worker job that succeeded with result or failed with error, as the
    worker writes its status: error_type is the class name of the exception that stopped it."""
    window.current_job = jobs.new_job(action, {})
    status = dict(phase='SUCCEEDED', action=action, result=result) if error is None else \
        dict(phase='FAILED', action=action, error=error, error_type=error_type)
    write_json(window.current_job / 'status.private.json', status)
    window.process = Mock()
    window.finished(0 if error is None else 2, None)


def finish_failed_job(window, error, action='direct_fl23_enable', error_type=None):
    """The banner after a job of `action` failed with `error`, any dialog the window would open answered
    at once."""
    from unittest.mock import patch
    from PySide6 import QtWidgets as W
    with patch.object(W.QMessageBox, 'information'), patch.object(W.QMessageBox, 'warning'):
        finish_job(window, action, error=error, error_type=error_type)
    return window.status.text()


def offline_smoke(name='offline_smoke_under_test'):
    """A fresh copy of dev/desktop/offline_smoke.py, the packaged self-test, loaded as module `name`."""
    spec = importlib.util.spec_from_file_location(name, Path(__file__).resolve().parent / 'offline_smoke.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
