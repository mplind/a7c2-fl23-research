"""With English chosen, no CJK character reaches anything the user sees during a camera job (Task 8b,
R38): the pages, every dialog the window opens, the log pane, the error and refusal banners, and the
macOS Terminal window that asks for the password. Chinese stays when Chinese is chosen, and the files
on disk stay verbatim. No camera, no worker, no Terminal: dialogs are read instead of shown.
"""
import json
from pathlib import Path
import re
from unittest.mock import Mock, patch

import pytest
from PySide6 import QtGui, QtWidgets as W

from desktopapp import engine_text, i18n, jobs, macadmin, presets, reloadguide
from desktopapp.en import STRINGS
from desktopapp.en_engine import ENGINE
from desktopapp.paths import write_json
from looktool import buildprofile, devicesession
from guihelpers import CJK, finish_job, shown_texts
from looksamples import look_file

SPECIFIER = re.compile(r'%(?:\([^)]+\))?[#0\- +]*\d*(?:\.\d+)?[diouxXeEfFgGcrsa%]')
SAMPLE = {'d': '7', 'i': '7', 'u': '7', 'x': '1f', 'X': '1F', 'o': '17', 'f': '2.5', 'F': '2.5', 'e': '2.5',
          'E': '2.5', 'g': '2.5', 'G': '2.5', 'c': 'c', '%': '%'}


def sample(template, value='disk4'):
    """`template` filled as the engine would fill it: numbers for numeric specifiers, `value` for text."""
    return SPECIFIER.sub(lambda m: SAMPLE.get(m.group()[-1], value), template)


def chinese(texts):
    return [text for text in texts if CJK.search(text)]


# The catalogues --------------------------------------------------------------------------------

def test_no_english_entry_holds_a_cjk_character():
    assert chinese(list(STRINGS.values()) + list(ENGINE.values())) == []


def test_engine_entries_keep_their_specifiers_in_order_and_their_line_count():
    for source, english in ENGINE.items():
        assert SPECIFIER.findall(source) == SPECIFIER.findall(english), source
        assert source.count('\n') == english.count('\n'), source


def test_no_message_is_catalogued_twice():
    assert sorted(set(STRINGS) & set(ENGINE)) == []


@pytest.mark.parametrize('source', sorted(ENGINE))
def test_every_engine_message_is_shown_in_english(source):
    english = ENGINE[source]
    shown = engine_text.translate_text(sample(source))
    assert shown == sample(english)
    assert not CJK.search(shown)
    for line in sample(source).split('\n'):
        assert not CJK.search(engine_text.translate_line(line)), line


@pytest.mark.parametrize('source', sorted(key for key in ENGINE if SPECIFIER.search(key)))
def test_a_catalogued_message_inside_another_is_translated_too(source):
    # A value the engine fills in can itself be a message: the macOS prompt after a wait, an error
    # inside a summary. Fill every %s with one and both come out English. (Two values side by side
    # are split at the first place the format allows, so the message chosen has no space.)
    inner = '相機正在準備機身資訊，稍候再讀取。'
    shown = engine_text.translate_text(sample(source, inner))
    assert not CJK.search(shown), shown
    assert engine_text.translate_text(inner) in shown or '%s' not in source


def test_every_interface_entry_also_reads_as_english_in_the_log():
    # A few interface texts reach the log too (the restart steps one-click setup prints).
    assert [key for key in STRINGS if CJK.search(engine_text.translate_text(sample(key)))] == []


@pytest.mark.parametrize('setup, mode', [(True, None), (True, 'resource_reload'), (False, None),
                                         (False, 'factory_reset'), (False, 'fl23_enable')])
def test_the_restart_steps_printed_by_one_click_setup_read_as_english(setup, mode):
    # allinone prints these guides into worker.log in Chinese; the window shows them in English.
    printed = '所有读写已结束。\n' + reloadguide.text(setup=setup, mode=mode)
    shown = engine_text.translate_text(printed)
    assert not CJK.search(shown), shown
    for line in printed.split('\n'):
        assert not CJK.search(engine_text.translate_line(line)), line


def test_unknown_text_such_as_a_camera_file_name_is_shown_unchanged():
    assert engine_text.translate_line('照片 0001.JPG') == '照片 0001.JPG'
    assert engine_text.translate_line('plain English stays') == 'plain English stays'


def test_display_translates_only_in_english():
    message = '正在卸载相机磁盘（不拔线）：disk4'
    i18n.configure('zh_CN')
    assert engine_text.display(message) == message
    i18n.configure('en')
    try:
        assert engine_text.display(message) == sample(ENGINE['正在卸载相机磁盘（不拔线）：%s'])
    finally:
        i18n.configure('zh_CN')


# The log pane and the banner -------------------------------------------------------------------

ENGINE_LINES = [
    '正在卸载相机磁盘（不拔线）：disk4',
    '服务模式已退出，等待普通 USB 连接（最多 60 秒）。若相机屏幕询问 USB 连接方式，请选择第 2 项「影像传输（MSC）」。',
    '读取相机程序文件以识别固件版本（只读）。',
    '正在写入程序窗口批次 3/12',
    '认证后相机未进入服务模式（期间出现的 Sony USB 身份：0e8a、0336）。',
    '{',
    '  "note": "通过只说明这段时间内连续只读传输稳定；不保证刷写期间一定不掉线，也不代表线材认证。",',
    '  "message": "所选安装已完成；请在机身检查预览、名称、拍摄和回放。竖屏已保存开启，并已核对重开后的实际运行状态。"',
    '}',
    'Traceback (most recent call last):',
    '  File "/Applications/A7C2Tools.app/Contents/Resources/src/camera_runtime/macos_host.py", line 95, in unmount_camera',
    "    raise RuntimeError('相机磁盘尚未稳定，尚未接管 USB。'+MSC_PROMPT+'等存取灯停止后重试。')",
    'RuntimeError: 相机磁盘尚未稳定，尚未接管 USB。若相机屏幕询问 USB 连接方式，请选择第 2 项「影像传输（MSC）」。等存取灯停止后重试。',
]


def test_the_log_pane_shows_worker_output_in_english_and_keeps_the_log_verbatim(window, tmp_path):
    ui = window('en')
    ui.current_job = jobs.new_job('connect', {})
    log = ui.current_job / 'worker.log'
    log.write_text('\n'.join(ENGINE_LINES) + '\n', encoding='utf-8')
    ui.tail_log()
    shown = ui.log.toPlainText()
    assert chinese(shown.split('\n')) == []
    assert sample(ENGINE['正在卸载相机磁盘（不拔线）：%s']) in shown
    assert "    raise RuntimeError('…'+MSC_PROMPT+'…')" in shown  # the code stays; its partial literals don't
    assert log.read_text(encoding='utf-8') == '\n'.join(ENGINE_LINES) + '\n'


def test_the_log_pane_keeps_chinese_in_the_chinese_interface(window):
    ui = window()
    ui.current_job = jobs.new_job('connect', {})
    (ui.current_job / 'worker.log').write_text(ENGINE_LINES[0] + '\n', encoding='utf-8')
    ui.tail_log()
    assert ui.log.toPlainText() == ENGINE_LINES[0]


def test_process_output_is_shown_in_english_and_saved_verbatim(window):
    ui = window('en')
    ui.current_job = jobs.new_job('connect', {})
    printed = '请在打开的「终端」窗口中输入 Mac 登录密码（输入时不显示）。\n'
    ui.process = Mock()
    ui.process.readAllStandardOutput.return_value = printed.encode('utf-8')
    ui.process_output()
    assert chinese([ui.log.toPlainText()]) == []
    assert (ui.current_job / 'process.log').read_text(encoding='utf-8') == printed


ERRORS = [
    '管理员进程意外结束，相机操作结果未知。请导出诊断包，不要重复刚才的操作。',
    '相机存储卷未能全部卸载，尚未接管 USB。请关闭照片、图像捕捉及使用存储卡的程序后重试。',
    '需要且只能連接一台目標相機（USB 0e8a）；請確認大量儲存模式及驅動',
    'USB 稳定性检测未通过（第 2 轮）：重复读回的字节不一致：/usr/lib/appFw.so。请换线或直连电脑 USB 接口后重测；本次没有固件或设置写入。',
    buildprofile.UNSUPPORTED % ('0123456789abcdef', 'fedcba9876543210'),
    buildprofile.JOB_OTHER_BUILD % ('public-2.01', 'body-2.01-20250923'),
    devicesession.UNIDENTIFIED,
]


@pytest.mark.parametrize('error', ERRORS)
def test_the_error_banner_is_english(window, error):
    ui = window('en')
    finish_job(ui, 'direct_verify', error=error)
    assert chinese([ui.status.text()]) == []


@pytest.mark.parametrize('language', ['en', 'zh_CN'])
def test_an_error_that_ends_its_sentence_gets_no_second_full_stop(window, language):
    ui = window(language)
    finish_job(ui, 'direct_verify', error=ERRORS[1])  # ends with 。, and in English with .
    assert '..' not in ui.status.text() and '。。' not in ui.status.text()


@pytest.mark.parametrize('error', ERRORS[:2])
def test_the_error_banner_keeps_chinese_in_the_chinese_interface(window, error):
    ui = window()
    finish_job(ui, 'direct_verify', error=error)
    assert error in ui.status.text()


def refused(folder, error):
    write_json(Path(folder, 'direct.private.json'), dict(phase='NEEDS_REVIEW', mode='factory_reset', error=error))
    write_json(Path(folder, 'setup.private.json'), dict(phase='NEEDS_REVIEW', error=error, options={}))
    return str(folder)


@pytest.mark.parametrize('error', [devicesession.UNIDENTIFIED, buildprofile.UNSUPPORTED % ('0' * 16, '1' * 16)])
def test_every_refusal_note_is_english(window, tmp_path, error):
    from desktopapp.paths import save_settings
    ui = window('en')
    folder = refused(tmp_path / 'refused', error)
    ui.settings.update(setup_work=folder, factory_direct_work=folder, look_direct_work=folder)
    save_settings(ui.settings)
    ui.refresh_setup_controls()
    ui.refresh_factory_controls()
    ui.refresh_look_controls()
    notes = [ui.setup_note.text(), ui.factory_status.text(), ui.look_pending.text()]
    assert all(notes) and chinese(notes) == []


# The pages and every dialog --------------------------------------------------------------------

class Shown:
    """Collects what each dialog would show instead of showing it; every question is answered Cancel."""

    def __init__(self, monkeypatch):
        self.texts = []

        def run(dialog, *args):
            self.texts += shown_texts(dialog)
            return 0

        def static(parent, title, text, *args, **kwargs):
            self.texts += [title, text]
            return W.QMessageBox.Ok
        monkeypatch.setattr(W.QDialog, 'exec', run)
        monkeypatch.setattr(W.QMessageBox, 'exec', run)
        for name in ('information', 'warning', 'question', 'critical'):
            monkeypatch.setattr(W.QMessageBox, name, static)

    def chinese(self):
        return chinese(self.texts)


def page_texts(ui):
    texts = [ui.windowTitle()] + [ui.nav.item(row).text() for row in range(ui.nav.count())]
    texts += [action.text() for action in ui.findChildren(QtGui.QAction)]
    for widget in ui.findChildren(W.QWidget):
        if widget is ui.language or widget is ui.settings_dialog or ui.settings_dialog.isAncestorOf(widget):
            continue
        texts += [text for text in shown_texts(widget) if widget is not ui.language]
    return texts


@pytest.mark.parametrize('platform', ['darwin', 'win32'])
def test_no_page_shows_cjk(window, platform):
    ui = window('en', platform=platform)
    ui.look_editor.add_row(3)
    seen = []
    for index in range(ui.pages.count()):
        ui.nav.setCurrentRow(index)
        seen += [ui.page_title.text(), ui.page_detail.text()]
    assert chinese(seen + page_texts(ui)) == []


def test_settings_shows_only_the_language_name_in_its_own_language(window):
    ui = window('en')
    texts = shown_texts(ui.settings_dialog)
    assert chinese(texts) == ['简体中文']
    assert [ui.language.itemText(i) for i in range(ui.language.count())] == ['English', '简体中文']


GUIDE_MODES = [None, 'factory_prewrite_temporary', 'factory_reset', 'resource_reload', 'fl23_enable', 'fl23_disable',
               'sound_confirm', 'sound_install', 'vertical_enable', 'vertical_disable', 'install_all']


def test_every_guide_and_help_dialog_is_english(window, monkeypatch, tmp_path):
    ui = window('en', platform='win32')
    shown = Shown(monkeypatch)
    for setup in (False, True):
        for mode in GUIDE_MODES:
            ui.show_reload_guide(setup=setup, mode=mode)
    for action in ui.findChildren(QtGui.QAction):
        if action.text() and action.menu() is None:
            action.trigger()
    ui.show_connection_notice()
    ui.show_zadig_guide()
    ui.show_look_format_guide()
    ui.compiler_dialog()
    ui.ask_drivers_first()
    ui.save_language()
    assert len(shown.texts) > 40 and shown.chinese() == []


def test_the_look_library_preview_and_hald_dialogs_are_english(window, monkeypatch, tmp_path):
    from desktopapp import looklibrary
    ui = window('en')
    shown = Shown(monkeypatch)
    path = look_file(tmp_path / 'look.a7look', mae=2.0, p95=7.0)
    monkeypatch.setattr(looklibrary, 'catalog', lambda: [dict(
        id='portra400', name='Portra 400', kind='negative', path=path, preview=False,
        fit={'rating': 'fair', 'mae': 3.0, 'p95': 9.0}, notes='', modification='m', shareable=True, swatches=None,
        source={'project': 'p', 'author': 'a', 'url': 'https://example.org', 'licence': 'CC0'})])
    ui.film_library_dialog()
    ui.preview_look(str(path))
    ui.preview_look(str(tmp_path / 'missing.a7look'))
    hald = tmp_path / 'identity.tif'
    with patch.object(W.QFileDialog, 'getSaveFileName', return_value=(str(hald), '')), \
            patch.object(W.QFileDialog, 'getOpenFileName', return_value=(str(hald), '')):
        ui.save_hald_identity()
        ui.check_hald_export()
    ui.look_editor.setEnabled(False)
    ui.add_library_look(dict(path=path), 1)
    assert len(shown.texts) > 10 and shown.chinese() == []


def test_every_write_confirmation_is_english(window, monkeypatch, tmp_path):
    ui = window('en')
    shown = Shown(monkeypatch)
    restore = ui.look_editor.add_row(3)
    write = ui.look_editor.add_row(4)
    write.action.setCurrentIndex(1)
    write.set_file(str(look_file(tmp_path / 'good.a7look', mae=2.0, p95=7.0, name='Good')))
    for button in ui.write_buttons:
        button.click()
    ui.setup_presets.setChecked(False)
    ui.fields['setup_look_2'].setText(str(look_file(tmp_path / 'poor.a7look', mae=6.0, p95=20.0)))
    ui.setup_button.click()
    common = dict(firmware='2.01', workspace=str(tmp_path / 'work'))
    ui.launch('direct_slot_default', dict(common, slot=2))
    ui.launch('direct_resume_looks', dict(common, failed_workspace=str(tmp_path / 'earlier')))
    ui.launch('restore_verify', dict(workspace=str(tmp_path / 'none'), accepted=False))
    for phase in ('AWAITING_RELOAD', 'WRITING'):
        with patch('looktool.factoryrecover.pending', return_value=(tmp_path / 'earlier', dict(phase=phase))):
            ui.factory_button.click()
    assert sum('ILCE-7CM2' in text for text in shown.texts) >= 10
    assert shown.chinese() == []
    assert restore  # the batch holds a restore and a write, so its target joins two items


def test_windows_only_confirmations_are_english(window, monkeypatch):
    ui = window('en', platform='win32')
    shown = Shown(monkeypatch)
    with patch('desktopapp.window.sys.platform', 'win32'):
        ui.launch('driver_uninstall', dict(pids=['0e8a', '0336']))
        ui.drivers_first(dict(workspace='/nowhere'))
    assert len(shown.texts) > 4 and shown.chinese() == []


def test_result_dialogs_and_notices_are_english(window, monkeypatch, tmp_path):
    from desktopapp.actions import recipe as job
    from desktopapp import recipes
    ui = window('en')
    shown = Shown(monkeypatch)
    plan = dict(ok=True, steps=[['write', 0xD0FA, 6, False]],
                writes=[dict(label='Creative Look', before='ST', after='FL', provisional=False),
                        dict(label='Contrast', before=None, after='-2', provisional=True)],
                problems=[dict(label='Position Key', reason='not offered', blocking=False)],
                recipe=job.recipe_args(recipes.PRESETS[0]), stop_ptpcamerad=True, camera_io='read_only')
    finish_job(ui, 'recipe_plan', plan)
    finish_job(ui, 'recipe_plan', dict(plan, ok=False, problems=[dict(label='Picture Profile', reason='PP3', blocking=True)]))
    finish_job(ui, 'recipe_plan', dict(plan, writes=[], steps=[]))
    finish_job(ui, 'recipe_apply', dict(written=[dict(label='Contrast', before='0', after='-2', provisional=False)]))
    finish_job(ui, 'usb_stability', dict(rounds=[{}, {}, {}], total_bytes=3 << 20, seconds=61.0,
                                         note='通过只说明这段时间内连续只读传输稳定；不保证刷写期间一定不掉线，也不代表线材认证。'))
    finish_job(ui, 'usb_stability', error='USB 稳定性检测未完成：已读 9 轮，达到轮数上限，但连续读取只持续 40 秒，未满 60 秒；本次不算通过。本次没有固件或设置写入。')
    finish_job(ui, 'sound_audition', dict(phase='temporary_pcm_registered_cold_reload_required_after_test'))
    finish_job(ui, 'sound_confirm', dict(phase='owner_confirmed_audio_cold_reload_required'))
    finish_job(ui, 'sound_install', dict(phase='sound_conversion_required'))
    finish_job(ui, 'direct_fl23_enable', dict(phase='COMPLETED', mode='fl23_enable', reload_required=True, workspace='w'))
    state = dict(phase='COMPLETE', options=dict(looks=[dict(slot=1, name='Kept name')], plugin=True))
    write_json(tmp_path / 'setup' / 'setup.private.json', state)
    ui.settings['setup_work'] = str(tmp_path / 'setup')
    ui.show_setup_result()
    ui.process = Mock()
    ui.closeEvent(Mock())
    ui.process = None
    with patch('desktopapp.actions.sound.has_conversion', return_value=False):
        ui.launch('sound_audition', dict(workspace=str(tmp_path / 'sound'), firmware='2.01'))
    with patch('desktopapp.actions.sound.has_conversion', side_effect=ValueError('当前声音文件长度与配置不同。')):
        ui.launch('sound_audition', dict(workspace=str(tmp_path / 'sound'), firmware='2.01'))
    ui.launch('direct_looks_import', dict(workspace=str(tmp_path / 'look'), firmware='2.01', operations=[]))
    assert len(shown.texts) > 20 and shown.chinese() == []


def test_an_unfinished_look_job_is_explained_in_english(window, monkeypatch, tmp_path):
    ui = window('en')
    shown = Shown(monkeypatch)
    prior = tmp_path / 'look'
    write_json(prior / 'direct.private.json', dict(phase='NEEDS_REVIEW', mode='install_all',
                                                   error='运行中程序与已记录的原状态／目标不符；保留日志，不自动重试'))
    ui.settings['look_direct_work'] = str(prior)
    with patch.object(QtGui.QDesktopServices, 'openUrl'):
        ui.launch_look_changes()
    assert shown.texts and shown.chinese() == []


# The macOS Terminal window ---------------------------------------------------------------------

def terminal_script(tmp_path, monkeypatch, language):
    monkeypatch.setenv('A7C2_DESKTOP_DATA', str(tmp_path / 'data'))
    request = tmp_path / ('job-' + language) / 'request.private.json'
    request.parent.mkdir()
    with patch('desktopapp.jobs.worker_command', return_value=['/Applications/A7C2Tools', '--worker', str(request)]):
        command = macadmin.command(request, 501, 20, {'HOME': '/Users/user', 'PATH': '/usr/bin'}, language=language)
    return Path(command[3]).read_text(encoding='utf-8')


def test_the_terminal_window_is_english_in_english(tmp_path, monkeypatch):
    script = terminal_script(tmp_path, monkeypatch, 'en')
    assert not CJK.search(script)
    assert 'Mac login password' in script


def test_the_terminal_window_is_chinese_in_chinese(tmp_path, monkeypatch):
    script = terminal_script(tmp_path, monkeypatch, 'zh_CN')
    assert '请在下方输入 Mac 登录密码' in script and '相机操作已结束' in script


def test_the_job_request_carries_the_interface_language_to_the_terminal(tmp_path, monkeypatch):
    monkeypatch.setenv('A7C2_DESKTOP_DATA', str(tmp_path / 'data'))
    for language in ('en', 'zh_CN'):
        i18n.configure(language)
        job = jobs.new_job('connect', {})
        assert json.loads((job / 'request.private.json').read_text(encoding='utf-8'))['language'] == language
        opened = []

        def run(argv, *args, **kwargs):
            opened.append(Path(argv[3]).read_text(encoding='utf-8'))
            (job / 'authorization.exit').write_text('closed\n', encoding='utf-8')
            from types import SimpleNamespace
            return SimpleNamespace(returncode=0, stdout='', stderr='')
        with patch.object(macadmin.os, 'getuid', return_value=501, create=True), \
                patch.object(macadmin.os, 'getgid', return_value=20, create=True), \
                patch.object(macadmin.subprocess, 'run', side_effect=run):
            macadmin.execute(job / 'request.private.json')
        assert bool(CJK.search(opened[0])) == (language == 'zh_CN')
    i18n.configure('zh_CN')


def test_the_terminal_script_still_runs_in_bash(tmp_path, monkeypatch):
    import shutil
    import subprocess
    bash = shutil.which('bash')
    if not bash:
        pytest.skip('bash is not installed')
    for language in ('en', 'zh_CN'):
        script = terminal_script(tmp_path, monkeypatch, language)
        checked = subprocess.run([bash, '-n'], input=script, text=True, encoding='utf-8', capture_output=True, timeout=30)
        assert checked.returncode == 0, checked.stderr
