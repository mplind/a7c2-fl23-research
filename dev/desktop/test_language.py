"""English interface: language persistence and identical GUI dispatch, with physical USB blocked.

Adapted from the display-only Korean localization on
Gureum-Yeoreum-Tori/a7c2-fl23-research (branch feat/korean-ui).
"""
import ast
import json
import os
from pathlib import Path
import re
from unittest.mock import Mock, patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import pytest
from PySide6 import QtWidgets as W
from desktopapp import i18n, jobs, reloadguide, completion
from desktopapp.en import STRINGS
from desktopapp.paths import write_json
from desktopapp.window import Window

HAN = re.compile('[㐀-鿿（），：；、。“”]')


@pytest.fixture
def ui(tmp_path, monkeypatch):
    monkeypatch.setenv('A7C2_DESKTOP_DATA', str(tmp_path))
    # Exercise the real new-install default, overriding the legacy Chinese fixture.
    from desktopapp.paths import load_settings
    monkeypatch.setattr('desktopapp.window.load_settings', load_settings)
    app = W.QApplication.instance() or W.QApplication([])
    windows = []
    def create(language=None):
        if language is not None:
            write_json(tmp_path / 'desktop.json', {'language': language})
        window = Window()
        window.timer.stop()
        windows.append(window)
        return window
    yield create, app, tmp_path
    for window in windows:
        window.process = None
        window.close()
    i18n.configure('zh_CN')


def visible_texts(window):
    """Every string the window shows: titles, labels, buttons, group boxes, lists and menus."""
    texts = [window.windowTitle()]
    texts += [window.nav.item(row).text() for row in range(window.nav.count())]
    for widget in window.findChildren(W.QWidget):
        if isinstance(widget, (W.QLabel, W.QAbstractButton)):
            texts.append(widget.text())
        if isinstance(widget, W.QGroupBox):
            texts.append(widget.title())
        if isinstance(widget, W.QLineEdit):
            texts.append(widget.placeholderText())
        if isinstance(widget, W.QComboBox) and widget is not window.language:
            texts += [widget.itemText(index) for index in range(widget.count())]
        texts.append(widget.toolTip())
    return [text for text in texts if text]


def test_new_install_defaults_to_english_and_no_page_shows_chinese(ui):
    create, app, _ = ui
    window = create()
    assert window.language.currentData() == 'en'
    assert window.nav.item(0).text() == 'Home · One-click install'
    assert window.setup_button.text() == 'One-click install'
    for index in range(window.pages.count()):
        window.nav.setCurrentRow(index)
        app.processEvents()
        assert window.pages.currentIndex() == index
    window.look_editor.add_row(4)
    chinese = [text for text in visible_texts(window) if HAN.search(text)]
    assert chinese == []
    assert window.common() == {'firmware': '2.01'}
    assert window.current_job is None


def test_language_selector_offers_english_and_chinese(ui):
    create, _, _ = ui
    window = create()
    assert [window.language.itemData(index) for index in range(window.language.count())] == ['en', 'zh_CN']
    assert window.language.itemText(1) == '简体中文'


def test_language_change_keeps_input_and_applies_on_next_launch(ui):
    create, _, root = ui
    window = create()
    window.fields['sound_source'].setText('/example/user 文件.wav')
    window.look_editor.add_row(4)
    with patch.object(W.QMessageBox, 'information'), patch.object(jobs, 'new_job') as job:
        window.language.setCurrentIndex(1)
    job.assert_not_called()
    settings = json.loads((root / 'desktop.json').read_text())
    assert settings['language'] == 'zh_CN'
    assert settings['sound_source'] == '/example/user 文件.wav'
    assert window.look_editor.values() == [{'slot': 4, 'action': 'restore'}]
    assert window.setup_button.text() == 'One-click install'
    reopened = create()
    assert reopened.nav.item(0).text() == '首页 · 一键安装'
    assert reopened.fields['sound_source'].text() == '/example/user 文件.wav'
    with patch.object(W.QMessageBox, 'information'):
        reopened.language.setCurrentIndex(0)
    assert create().setup_button.text() == 'One-click install'


@pytest.mark.parametrize('language', ['en', 'zh_CN'])
def test_language_does_not_change_worker_action_or_slot_data(ui, language):
    create, _, _ = ui
    window = create(language)
    row = window.look_editor.add_row(4)
    row.action.setCurrentIndex(1)
    row.set_file('/example/source 文件.a7look')
    row.name.setText('My look 原名')
    assert window.look_batch_args()['operations'] == [dict(
        slot=4, action='write', path='/example/source 文件.a7look', name='My look 原名')]
    window.look_editor.set_operations([dict(slot=4, action='restore')])
    with patch.object(W.QMessageBox, 'question', return_value=W.QMessageBox.Yes), \
            patch('desktopapp.window.QtCore.QProcess'):
        window.look_button.click()
    request = json.loads((window.current_job / 'request.private.json').read_text())
    assert request['action'] == 'direct_looks_import'
    assert request['arguments']['operations'] == [dict(slot=4, action='restore')]
    assert request['arguments']['firmware'] == '2.01'
    assert request['arguments']['power_confirmed'] is True
    assert not window.language.isEnabled()


def test_english_write_confirmation_can_cancel_without_creating_job(ui):
    create, _, _ = ui
    window = create()
    window.look_editor.add_row(3)
    with patch.object(W.QMessageBox, 'question', return_value=W.QMessageBox.Cancel) as confirm, \
            patch.object(jobs, 'new_job') as new:
        window.look_button.click()
    new.assert_not_called()
    title, text = confirm.call_args.args[1:3]
    assert title == 'Start writing to the camera'
    assert 'ILCE-7CM2' in text and '2.01' in text and '50%' in text
    assert 'Custom 3' in text
    assert not HAN.search(title + text)


def test_safety_guides_and_completion_are_english_without_translating_user_names(ui):
    create, _, _ = ui
    create('en')
    guide = reloadguide.text()
    assert 'at least 1 minute' in guide and not HAN.search(guide)
    assert 'not yet written' in reloadguide.text(mode='resource_reload')
    notice = reloadguide.sound_notice('sound_audition', dict(
        phase='temporary_pcm_registered_cold_reload_required_after_test'))
    assert 'Keep the camera switched on' in notice['title']
    state = dict(phase='COMPLETE', options=dict(looks=[dict(slot=1, name='原名 kept')]))
    assert '原名 kept' in completion.text(state)
    assert 'selected operations are complete' in completion.text(state)
    create('zh_CN')
    assert '至少等待 1 分钟' in reloadguide.text()


def finish_failed_job(window, root, error):
    job = root / 'runs' / 'failed-job'; job.mkdir(parents=True)
    write_json(job / 'status.private.json', dict(phase='FAILED', action='direct_verify', error=error))
    window.current_job, window.process = job, Mock()
    with patch.object(W.QMessageBox, 'information'), patch.object(W.QMessageBox, 'warning'):
        window.finished(2, None)
    return window.status.text()


@pytest.mark.parametrize('error,english', [
    ('管理员进程意外结束，相机操作结果未知。请导出诊断包，不要重复刚才的操作。', 'result is unknown'),
    ('终端授权未完成（窗口已关闭或密码不正确）；本次相机操作尚未开始，可重新点击原按钮。', 'has not started'),
    ('尚未确认新的冷启动。完成断电重开后再核对，不要重复写入。', 'do not repeat the write'),
])
def test_safety_critical_worker_errors_are_shown_in_english(ui, error, english):
    create, _, root = ui
    text = finish_failed_job(create(), root, error)
    assert text.startswith('Operation stopped: ') and english in text
    assert not HAN.search(text)


def test_other_worker_errors_are_shown_verbatim_inside_the_english_frame(ui):
    create, _, root = ui
    text = finish_failed_job(create(), root, '读取 appFw.so 失败：0x3528804')
    assert text == 'Operation stopped: 读取 appFw.so 失败：0x3528804. Please export diagnostics.'


def test_english_entries_keep_format_specifiers_and_file_extensions():
    specifiers = re.compile(r'%(?:\([^)]+\))?[#0\- +]*\d*(?:\.\d+)?[diouxXeEfFgGcrsa%]')
    for source, english in STRINGS.items():
        assert specifiers.findall(source) == specifiers.findall(english), source
        for extension in re.findall(r'\*\.[A-Za-z0-9]+', source):
            assert extension in english, source
        assert not HAN.search(english), source
    assert i18n.tr('unmapped diagnostic') == 'unmapped diagnostic'


def test_every_translated_display_literal_has_an_english_entry():
    root = Path(__file__).resolve().parents[2] / 'src/desktopapp'
    missing = []
    for name in ('window.py', 'lookeditor.py', 'reloadguide.py', 'completion.py'):
        tree = ast.parse((root / name).read_text(encoding='utf-8'))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == 'tr':
                if node.args and isinstance(node.args[0], ast.Constant) and node.args[0].value not in STRINGS:
                    missing.append((name, node.lineno, node.args[0].value[:30]))
    assert missing == []


def test_windows_driver_controls_and_zadig_guide_use_english(ui):
    create, _, _ = ui
    with patch('desktopapp.window.sys.platform', 'win32'):
        window = create('en')
    automatic = window.findChild(W.QPushButton, 'action_usb_prepare')
    zadig = window.findChild(W.QPushButton, 'zadig_guide')
    assert automatic.text() == 'Prepare two-stage drivers & test connection (automatic)'
    assert zadig.text().startswith('Install with Zadig')
    from desktopapp.zadigguide import TEXT
    assert '054C 0336' in i18n.tr(TEXT) and 'administrator' in i18n.tr(TEXT)
