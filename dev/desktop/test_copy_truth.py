"""Task 8c (R54): what the window says matches what each control does. No camera, no worker: dialogs
are read instead of shown, and QProcess is mocked by the window fixture."""
import re
from pathlib import Path
from unittest.mock import patch

import pytest
from PySide6 import QtWidgets as W

from desktopapp import i18n, jobs, reloadguide, shell
from desktopapp.en import STRINGS
from guihelpers import HAN_OR_PUNCTUATION, finish_job


def plain(text):
    """`text` with typographic apostrophes as straight ones, for comparing."""
    return text.replace('\u2019', "'")


def menu_actions(ui, title):
    return next(menu for menu in ui.menuBar().findChildren(W.QMenu) if menu.title() == title).actions()


def shown_information(ui, trigger):
    """(title, text) of the information alert `trigger()` opens."""
    with patch.object(W.QMessageBox, 'information') as alert:
        trigger()
    assert alert.call_count == 1
    return alert.call_args.args[1:3]


def row_of(button):
    """The ActionRow a button sits in."""
    widget = button.parentWidget()
    while widget is not None and not isinstance(widget, shell.ActionRow):
        widget = widget.parentWidget()
    return widget


def row_buttons(row):
    return [row.controls.itemAt(i).widget() for i in range(row.controls.count())]


# 1. The cold-restart steps from the Help menu and the guide buttons ---------------------------------

def test_the_help_menu_cold_restart_steps_have_their_own_title_and_only_the_steps(window):
    # The Help menu works during a write; it must never say reading and writing have ended.
    ui = window('en')
    action = next(a for a in menu_actions(ui, 'Help') if a.text() == 'How to cold restart…')
    manual = shown_information(ui, action.trigger)
    after_task = shown_information(ui, lambda: ui.show_reload_guide())
    assert manual[0] == 'How to cold restart' != after_task[0]
    assert 'Reading and writing have ended. Cold restart' in after_task[0]
    assert manual[1] == i18n.tr(reloadguide.STEPS)
    assert 'Next:' not in manual[1]


def test_every_how_to_cold_restart_button_opens_the_same_steps(window):
    ui = window('en')
    guides = [b for b in ui.findChildren(W.QPushButton) if b.text() == 'How to cold restart…']
    assert len(guides) == 4  # Factory restore, FL2 / FL3, Shutter sound, backup restore
    for guide in guides:
        assert shown_information(ui, guide.click) == ('How to cold restart', i18n.tr(reloadguide.STEPS))


# 2. The banner while a task runs ---------------------------------------------------------------------

@pytest.mark.parametrize('action, arguments, camera', [
    ('direct_fl23_enable', dict(firmware='2.01', workspace='w'), True),
    ('connect', {}, True),
    ('compile_look', dict(source='a.cube', name='n', output='o.a7look', model='m'), False),
    ('sound_import', dict(workspace='s', source='a.wav', start=0, duration=.5, peak=.4), False),
])
def test_the_running_banner_says_whether_the_camera_is_in_use_and_names_no_action(window, action, arguments, camera):
    ui = window('en')
    with patch('desktopapp.window.ask', return_value=True):
        ui.launch(action, arguments)
    text = plain(ui.status.text())
    assert action not in text and '_' not in text
    if camera:
        assert text == "Working with the camera. Don't switch it off or unplug it until this finishes."
    else:
        assert text == 'Working on this computer. Nothing is written to the camera.'
    assert not HAN_OR_PUNCTUATION.search(text)


# 3. The write confirmation -----------------------------------------------------------------------------

def confirmation(ui, action, arguments):
    with patch('desktopapp.window.ask', return_value=False) as ask, \
            patch('desktopapp.actions.sound.has_conversion', return_value=True):
        ui.launch(action, arguments)
    assert ask.call_count == 1
    return plain(ask.call_args.args[2])


def test_the_write_confirmation_makes_the_click_the_battery_check_and_says_the_app_checks_the_build(window):
    ui = window('en')
    text = confirmation(ui, 'direct_fl23_enable', dict(firmware='2.01', workspace='w'))
    assert "can't read the level" in text and 'clicking Write to camera confirms it' in text
    assert 'at least 50%' in text
    assert 'the app checks the camera is an' in text and 'ILCE-7CM2' in text and '2.01' in text
    assert 'Check the camera is an ILCE-7CM2' not in text
    assert "Don't switch it off or unplug it" in text


@pytest.mark.parametrize('action, target', [
    ('vertical_enable', 'Vertical display on, with the Fn and submenu fixes'),
    ('vertical_disable', 'Vertical display off, and the Fn and submenu fixes removed'),
    ('sound_on', 'Electronic shutter sound on'),
    ('sound_off', 'Electronic shutter sound off'),
    ('sound_audition', 'Trial of the converted sound, until the camera is switched off'),
    ('sound_install', "The converted sound, saved to the camera (the shutter sound is turned on if it's off)"),
    ('sound_restore_sound', "Sony's original shutter sound"),
])
def test_vertical_and_sound_confirmations_say_what_is_written_not_a_folder(window, tmp_path, action, target):
    ui = window('en')
    folder = str(tmp_path / 'records-folder')
    text = confirmation(ui, action, dict(firmware='2.01', workspace=folder, backup=folder + '-backup'))
    assert 'Target: ' + target + '\n' in text
    assert 'records-folder' not in text


# 4. Factory restore ------------------------------------------------------------------------------------

def factory_record(ui, tmp_path, phase, **values):
    import json
    from desktopapp.paths import save_settings
    folder = tmp_path / 'factory-job'
    folder.mkdir(exist_ok=True)
    (folder / 'direct.private.json').write_text(json.dumps(dict(mode='factory_reset', phase=phase, **values)),
                                                encoding='utf-8')
    ui.settings['factory_direct_work'] = str(folder)
    save_settings(ui.settings)
    ui.refresh_factory_controls()


def test_the_relabelled_finish_button_shows_it_can_write_and_its_status_names_it(window, tmp_path):
    ui = window('en')
    factory_record(ui, tmp_path, 'AWAITING_RELOAD')
    assert ui.factory_button.text() == 'Verify and finish…'
    status = ui.factory_status.text()
    assert 'Verify and finish' in status and 'writes again only if the camera has changed' in status
    assert ui.factory_button in row_buttons(row_of(ui.factory_button))


@pytest.mark.parametrize('values, button', [
    (dict(failed_during='READING', journal=[]), 'Restore'),
    (dict(failed_during='READING', journal=[], error='相机执行插件仍存在，不能在执行期间覆盖；本次尚未恢复写入，请结束连接后完整断电再重试'),
     'Retry restore'),
])
def test_no_factory_status_points_to_a_button_above(window, tmp_path, values, button):
    for language in ('en', 'zh_CN'):
        ui = window(language)
        factory_record(ui, tmp_path, 'NEEDS_REVIEW', **values)
        status = ui.factory_status.text()
        assert 'above' not in status and '上方' not in status
        if language == 'en':
            assert ('click ' + button) in status.replace('Click', 'click')
            assert ui.factory_button.text().rstrip('…') == button


def test_the_factory_restore_dialog_names_one_verify_control(window):
    ui = window('en')
    _, text = shown_information(ui, lambda: ui.show_reload_guide(mode='factory_reset'))
    next_step = text.split('Next:')[1]
    assert 'Verify and finish' in next_step
    assert 'beside' not in next_step and next_step.count('Verify') == 1
    i18n.configure('zh_CN')
    chinese = reloadguide.text(mode='factory_reset')
    assert '重启后核对并完成恢复（恢复写入后必做）' not in chinese and '上方' not in chinese


# 5. macOS: no rows that repeat Detect or Test, or do nothing --------------------------------------------

@pytest.mark.parametrize('platform, shown', [('darwin', False), ('win32', True)])
def test_the_usb_prepare_and_driver_rows_show_on_windows_only(window, platform, shown):
    ui = window('en', platform=platform)
    for name in ('action_usb_prepare', 'action_driver_install'):
        assert (ui.findChild(W.QPushButton, name) is not None) == shown, name
    labels = [label.text() for label in ui.findChildren(W.QLabel)]
    assert ('Driver target' in labels) == shown
    assert ui.findChild(W.QPushButton, 'action_driver_scan') is not None
    assert ui.findChild(W.QPushButton, 'action_connect') is not None


# 6. One row per feature, both buttons in it -----------------------------------------------------------

@pytest.mark.parametrize('pair, labels', [
    (('direct_fl23_disable', 'direct_fl23_enable'), ['Remove…', 'Enable…']),
    (('vertical_disable', 'vertical_enable'), ['Turn off…', 'Turn on…']),
    (('sound_off', 'sound_on'), ['Turn off…', 'Turn on…']),
])
def test_each_switch_is_one_row_with_both_buttons_that_launch_as_before(window, pair, labels):
    ui = window('en')
    buttons = [ui.findChild(W.QPushButton, 'action_' + action) for action in pair]
    row = row_of(buttons[0])
    assert row is row_of(buttons[1]) and row_buttons(row) == buttons
    assert [b.text() for b in buttons] == labels
    launched = []
    with patch.object(ui, 'launch', side_effect=lambda action, arguments: launched.append((action, arguments))):
        for button in buttons:
            button.click()
    assert [action for action, _ in launched] == list(pair)
    if 'fl23' in pair[0]:
        assert [arguments['workspace'] != '' for _, arguments in launched] == [True, True]
    else:
        assert launched[0][1] == launched[1][1]  # the same page arguments, as before


def test_the_vertical_records_folder_sits_in_a_closed_disclosure(window):
    ui = window('en')
    page = ui.pages.widget(5).widget()
    assert ui.page_meta[5][0] == 'Vertical display'
    field = ui.fields['vertical_work']
    disclosure = next(t for t in page.findChildren(W.QToolButton) if t.text() == 'Records folder')
    assert not disclosure.isChecked() and not field.isVisibleTo(page)
    disclosure.setChecked(True)
    assert field.isVisibleTo(page)
    headings = [label.text() for label in page.findChildren(W.QLabel) if label.property('role') == 'headline']
    assert 'Vertical display' not in headings  # the page title is not repeated as a group heading


def test_sonys_original_sound_sits_with_the_custom_shutter_sound(window):
    ui = window('en')
    restore = ui.findChild(W.QPushButton, 'action_sound_restore_sound')
    save = ui.findChild(W.QPushButton, 'action_sound_install')
    verify = ui.findChild(W.QPushButton, 'action_sound_verify')
    group = lambda button: row_of(button).parentWidget().parentWidget()  # row → its frame → the Group
    assert group(restore) is group(save)
    assert group(verify) is not group(save)
    assert plain(row_of(restore).title.text()) == "Sony's original sound"


# 7. The ellipsis --------------------------------------------------------------------------------------

def test_every_camera_write_button_ends_with_an_ellipsis_and_no_immediate_button_does(window):
    ui = window('en')
    writes = [b for b in ui.write_buttons if b.objectName() != 'action_direct_looks_import']
    assert len(writes) >= 12 and [b.text() for b in writes if not b.text().endswith('…')] == []
    assert ui.look_button.text().endswith('…')
    immediate = ['action_driver_scan', 'action_connect', 'action_usb_stability', 'action_mac_unmount',
                 'action_sound_import', 'action_direct_verify', 'action_sound_verify', 'action_restore_verify',
                 'action_factory_prepare', 'action_backup_inspect', 'action_sound_confirm', 'action_recipe_plan']
    texts = {name: ui.findChild(W.QPushButton, name).text() for name in immediate}
    assert [name for name, text in texts.items() if text.endswith('…')] == []
    tools = {b.text() for b in ui.findChildren(W.QPushButton)}
    assert 'Install' in tools and 'Install…' in tools  # the plugin starts at once; one-click opens the confirmation
    assert 'Show in Finder' in tools and 'Open' not in tools


@pytest.mark.parametrize('state, label', [(None, 'Install…'), ('pending', 'Continue installation…'),
                                          ('COMPLETE', 'Start a new installation…')])
def test_the_install_button_has_its_own_label_in_every_state(window, tmp_path, state, label):
    import json
    from desktopapp.paths import save_settings
    ui = window('en')
    if state:
        folder = tmp_path / 'setup'
        folder.mkdir()
        (folder / 'setup.private.json').write_text(json.dumps(dict(
            phase='COMPLETE' if state == 'COMPLETE' else 'WAIT_RELOAD', options={})), encoding='utf-8')
        ui.settings['setup_work'] = str(folder)
        save_settings(ui.settings)
        ui.refresh_setup_controls()
    assert ui.setup_button.text() == label
    ui.nav.setCurrentRow(0)
    assert ui.page_title.text() == 'One-click install'


# 8. The page title and the button are separate catalogue entries --------------------------------------

def test_the_install_button_and_the_page_title_are_separate_entries():
    assert STRINGS['一键安装'] == 'One-click install'
    assert STRINGS['一键安装…'] == 'Install…'


# 12. The saved summary ---------------------------------------------------------------------------------

def test_the_saved_summary_button_and_its_lines_say_it_reads_a_file(window, tmp_path):
    import json
    from desktopapp import completion
    ui = window('en')
    assert ui.setup_result_button.text() == 'Show saved summary'
    folder = tmp_path / 'setup'
    folder.mkdir()
    (folder / 'setup.private.json').write_text(json.dumps(dict(phase='COMPLETE', options={})), encoding='utf-8')
    ui.settings['setup_work'] = str(folder)
    with patch.object(W.QMessageBox, 'information'):
        finish_job(ui, 'setup_all', dict(phase='COMPLETE', workspace=str(folder)))
    assert plain(ui.status.text()) == "Installation complete. Show saved summary opens this again; it doesn't use the camera."
    assert plain(completion.text(dict(phase='COMPLETE', options={}))).endswith(
        "This summary is saved on this computer; showing it doesn't use the camera.")


# 10. The failure banner adds "Export diagnostics" only where the error gives no next step of its own ----

OWN_STEP = '终端授权未完成（窗口已关闭或密码不正确）；本次相机操作尚未开始，可重新点击原按钮。'
NO_STEP = '读取 appFw.so 失败：0x3528804'


def test_the_english_failure_banner_adds_export_diagnostics_only_when_the_error_has_no_next_step(window):
    from desktopapp.engine_text import display
    ui = window('en')
    suffix = '. Export diagnostics to report it.'
    finish_job(ui, 'direct_verify', error=OWN_STEP)
    own = ui.status.text()
    assert suffix not in own and 'diagnostics' not in own
    assert own.rstrip('.') == 'Stopped: ' + display(OWN_STEP).rstrip('.')
    finish_job(ui, 'direct_verify', error=NO_STEP)
    assert ui.status.text().endswith(suffix)


@pytest.mark.parametrize('error', [OWN_STEP, '当前声音文件长度与配置不同。', NO_STEP])
def test_the_chinese_failure_banner_always_adds_export_diagnostics(window, error):
    # R57 I-1: NEXT_STEP was chosen from the English, which gives some errors a next step their Chinese
    # source lacks (当前声音文件长度与配置不同。 says only what is wrong). Chinese keeps its suffix.
    ui = window('zh_CN')
    finish_job(ui, 'direct_verify', error=error)
    assert ui.status.text() == '操作停止：' + error.rstrip('。') + '。请导出诊断包。'


def test_every_error_said_to_give_its_own_next_step_is_a_catalogued_message():
    from desktopapp.en_engine import ENGINE, NEXT_STEP
    assert sorted(NEXT_STEP - set(ENGINE)) == []
    assert OWN_STEP in NEXT_STEP and NO_STEP not in NEXT_STEP


# Fix round 1 (R57) ------------------------------------------------------------------------------------

# Words that make an English error's own next step: what the user does now.
NEXT_STEP_WORDS = ('Click', 'click', 'cold restart', 'Export diagnostics', 'export diagnostics', 'try again',
                   'Try again', 'Reinstall', 'Turn on', 'Unplug', 'Choose', 'Reconnect', 'Quit', 'Wait for',
                   'Keep the log', 'Save the sound again', 'Move the start', 'move the start', 'Connect one',
                   'Add at least', "Don't repeat", 'run a factory restore', 'test again', 'Use "Prepare',
                   'Run its action first', 'check the network', 'Check the network', 'read the camera again',
                   'Convert the clip first')


def test_every_error_listed_with_its_own_next_step_gives_one_in_english():
    # The /usr refusals take their step from the message checkpointworker fills in (REBOOT): read them so.
    from desktopapp.en_engine import ENGINE, NEXT_STEP
    from looktool.checkpointworker import REBOOT

    def shown(key):
        return ENGINE[key].replace('%s', ENGINE[REBOOT], 1) if key.startswith(('相机 /usr', '写入前检查')) else ENGINE[key]
    assert sorted(key for key in NEXT_STEP if not any(word in shown(key) for word in NEXT_STEP_WORDS)) == []


def test_the_write_confirmation_keeps_the_caution_the_build_check_cannot_cover(window):
    # R57 I-2: identify() puts the regions this tool manages back to stock before it compares, so another
    # tool's change inside them passes; the confirmation says so, as compat.WARNING does.
    for language, words in (('en', "inside the regions this tool manages aren't detected and may conflict"),
                            ('zh_CN', '本工具管理区域内')):
        ui = window(language)
        text = confirmation(ui, 'direct_fl23_enable', dict(firmware='2.01', workspace='w'))
        assert words in text
    english = plain(confirmation(window('en'), 'direct_fl23_enable', dict(firmware='2.01', workspace='w')))
    assert 'outside the regions this tool manages' in english  # what the build check covers, and no more


@pytest.mark.parametrize('phase, english', [('DRIVERS', 'One-click install: preparing the USB connection'),
                                            ('INSTALLING', 'One-click install: writing the selected features'),
                                            ('WAIT_RELOAD', 'One-click install: paused for the cold restart and check')])
def test_a_chunk_of_one_click_lines_reads_each_line_by_its_own_entry(phase, english):
    # R57 I-3: allinone prints the phase, then the step it runs, so the window reads both in one chunk.
    from desktopapp import engine_text
    action = {'DRIVERS': 'usb_prepare', 'INSTALLING': 'direct_install_all', 'WAIT_RELOAD': 'direct_verify'}[phase]
    chunk = '一键安装：' + phase + '\n执行：' + action
    shown = engine_text.translate_text(chunk).split('\n')
    assert shown == [english, engine_text.translate_line('执行：' + action)]
    assert phase not in shown[0] and not re.search(r'\b%s\b' % re.escape(action), shown[1])


def test_every_step_the_one_click_job_runs_has_a_name_in_the_log():
    # R57 C2: the log shows what each step is, not its action id; worker.log keeps the id.
    import ast
    from desktopapp import allinone, engine_text
    tree = ast.parse(Path(allinone.__file__).read_text(encoding='utf-8'))
    actions = {node.args[0].value for node in ast.walk(tree) if isinstance(node, ast.Call)
               and isinstance(node.func, ast.Name) and node.func.id == 'call' and node.args
               and isinstance(node.args[0], ast.Constant)}
    assert len(actions) >= 10
    for action in sorted(actions):
        shown = engine_text.translate_line('执行：' + action)
        assert not re.search(r'\b%s\b' % re.escape(action), shown) and '_' not in shown, shown


def test_the_connection_page_gives_each_row_and_field_its_own_name(window):
    # R57 C3: the volume field and the Eject row no longer share "Camera volume".
    ui = window('en')
    page = ui.pages.widget(1).widget()
    names = [label.text() for label in page.findChildren(W.QLabel)
             if label.text() and label.property('role') not in ('callout',)]
    assert names.count('Camera volume') == 1
    eject = ui.findChild(W.QPushButton, 'action_mac_unmount')
    assert row_of(eject).title.text() != 'Camera volume'


def test_the_factory_restore_confirmation_says_what_the_page_says(window):
    # R57 C4: the same scope on the page and in the confirmation.
    ui = window('en')
    ui.nav.setCurrentRow(2)
    text = plain(confirmation(ui, 'direct_factory_reset', dict(firmware='2.01', workspace='w', factory='builtin')))
    page = plain(ui.page_detail.text())
    puts_back = ("Puts Sony's original program bytes and look names back wherever this tool changed them "
                 '(FL2 and FL3, looks, the shutter sound, vertical display) and resets Custom 1–6 to ST')
    assert puts_back in page and puts_back in text
    # I-1: neither removes the saved custom sound's files (test_port_factory pins the plan's scope).
    assert 'A saved custom shutter sound stays on the camera, unused.' in page
    assert 'A saved custom shutter sound stays on the camera, unused.' in text
    assert "earlier Custom 1–6 settings aren't recovered" in page and "earlier Custom 1–6 settings aren't recovered" in text


@pytest.mark.parametrize('source', [
    '恢复完成，所有读写已结束。拔 USB 和其他外部供电，等存取灯停止闪烁，再正常关机并等屏幕和灯完全熄灭；取下电池至少一分钟，再装回开机、检查并核对。',
    '续接写入和读回已结束，恢复尚未完成：请拔 USB 和其他外部供电，等存取灯停止闪烁，再正常关机并等屏幕和灯完全熄灭；取下电池至少一分钟，再装回开机、接回 USB，点击“重启后核对并完成恢复”。',
    '恢复尚未完成：本次写入和完整读回已结束，还必须重启后核对相机实际加载状态。\n\n',
])
def test_lines_that_end_camera_io_start_with_the_guides_cue(source):
    # R57 M-1: the cold-restart guide waits for exactly this phrase.
    from desktopapp.en_engine import ENGINE
    english = ENGINE.get(source) or STRINGS[source]
    assert english.startswith('Reading and writing have ended.')


def test_constant_write_targets_come_from_one_table():
    # R57 M-5: every target that doesn't depend on the arguments is in WRITE_TARGETS.
    from desktopapp import window as window_module
    assert {'direct_factory_reset', 'direct_fl23_enable', 'direct_fl23_disable'} <= set(window_module.WRITE_TARGETS)


@pytest.mark.parametrize('action, target', [('direct_factory_reset', 'Factory state (firmware 2.01)'),
                                            ('direct_fl23_enable', 'FL2/FL3: enable'),
                                            ('direct_fl23_disable', 'FL2/FL3: remove from list')])
def test_constant_direct_targets_are_unchanged(window, action, target):
    ui = window('en')
    text = confirmation(ui, action, dict(firmware='2.01', workspace='w', factory='builtin'))
    assert 'Target: ' + target + '\n' in text


def test_no_row_title_repeats_another_on_its_page_or_the_page_title(window):
    # R57 M-6: each row says what it is; none repeats a sibling's title or the page's.
    ui = window('en')
    for index in range(ui.pages.count()):
        page = ui.pages.widget(index).widget()
        titles = [row.title.text() for row in page.findChildren(shell.ActionRow)]
        repeated = sorted({title for title in titles if titles.count(title) > 1})
        assert repeated == [], (ui.page_meta[index][0], repeated)
        assert ui.page_meta[index][0] not in titles, ui.page_meta[index][0]
