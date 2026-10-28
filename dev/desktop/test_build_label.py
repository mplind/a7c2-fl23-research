"""The camera's firmware build on the Connection page, writes disabled on an unsupported build, and no
resume offered for a job a firmware refusal stopped. No camera and no USB: the worker runs over the
production session classes on an in-memory link (test_firmware_gate), and the refused jobs are what
the real engine leaves on disk when the gate refuses a camera of no supported build.
"""
import json
from pathlib import Path
from unittest.mock import Mock, patch

import pytest
from PySide6 import QtWidgets as W

from desktopapp import i18n, jobs, worker
from desktopapp.en import STRINGS
from desktopapp.paths import data_root, write_json
from looktool import buildprofile, checkpointworker, devicesession
from looktool.buildprofile import BUILDS, UnsupportedFirmware

from guihelpers import HAN  # noqa: E402
from test_firmware_gate import AP, CP, UNKNOWN, GateCamera  # noqa: E402

PUBLIC, BODY = BUILDS
PUBLIC_LABEL = 'Sony 2.01 (public update)'
BODY_LABEL = 'Sony 2.01 (camera build, 23 Sep 2025)'
UNSUPPORTED_LABEL = 'Unsupported firmware build: changes are disabled'
NOT_CHECKED = 'Not checked yet'


# The window ------------------------------------------------------------------------------------

def connect_result(key):
    return dict(model='ILCE-7CM2', service_connected=True, firmware_programs_written=False, firmware_build=key)


def finish(window, action, result=None, error=None, error_type=None):
    """Let window.finished() handle a worker job that succeeded with `result`, or failed with `error`
    (the status file the worker writes: its error_type is the exception's class name)."""
    window.current_job = jobs.new_job(action, {})
    status = (dict(phase='SUCCEEDED', action=action, result=result) if error is None else
              dict(phase='FAILED', action=action, error=error, error_type=error_type))
    write_json(window.current_job / 'status.private.json', status)
    window.process = Mock()
    window.finished(0 if error is None else 2, None)


def write_buttons(ui):
    """Every button that starts a camera write, found by the action it launches (the window's own list
    of them is what is under test)."""
    return [button for button in ui.findChildren(W.QPushButton)
            if button.objectName() == 'one_click_restore'
            or (button.objectName().startswith('action_') and button.objectName()[len('action_'):] in jobs.POWER_ACTIONS)]


def enabled(buttons):
    return sorted(button.objectName() for button in buttons if button.isEnabled())


@pytest.mark.parametrize('key, english', [
    (PUBLIC.key, PUBLIC_LABEL), (BODY.key, BODY_LABEL), (None, UNSUPPORTED_LABEL)])
def test_connection_test_shows_the_cameras_build(window, key, english):
    ui = window('en')
    finish(ui, 'connect', connect_result(key))
    assert ui.build_label.text() == english
    assert not HAN.search(ui.build_label.text())


def test_every_supported_build_has_its_english_label():
    assert [STRINGS[build.label_zh] for build in BUILDS] == [PUBLIC_LABEL, BODY_LABEL]


@pytest.mark.parametrize('key, chinese', [
    (PUBLIC.key, PUBLIC.label_zh), (BODY.key, BODY.label_zh), (None, '固件版本不受支持：已禁用更改')])
def test_chinese_interface_shows_the_chinese_source(window, key, chinese):
    ui = window()
    finish(ui, 'connect', connect_result(key))
    assert ui.build_label.text() == chinese


def test_build_line_is_on_the_connection_page_and_starts_unchecked(window):
    ui = window('en')
    assert ui.build_label.text() == NOT_CHECKED
    assert ui.pages.widget(1).isAncestorOf(ui.build_label)
    assert enabled(write_buttons(ui)) == sorted(button.objectName() for button in write_buttons(ui)
                                                if button.objectName() != 'action_direct_looks_import')


def test_an_unknown_build_changes_the_line_style(window):
    ui = window('en')
    finish(ui, 'connect', connect_result(None))
    assert ui.build_label.property('warning') is True
    finish(ui, 'connect', connect_result(PUBLIC.key))
    assert not ui.build_label.property('warning')


@pytest.mark.parametrize('result', [dict(model='ILCE-7CM2', service_connected=True), connect_result('public-2.02')],
                         ids=['not reported', 'unknown key'])
def test_a_build_the_worker_did_not_name_correctly_never_shows_as_supported(window, result):
    ui = window('en')
    finish(ui, 'connect', connect_result(PUBLIC.key))
    finish(ui, 'connect', result)
    if 'firmware_build' in result:   # a key no build has: fail closed
        assert ui.build_label.text() == UNSUPPORTED_LABEL
        assert enabled(write_buttons(ui)) == []
    else:                            # an older worker says nothing: the last answer stands
        assert ui.build_label.text() == PUBLIC_LABEL


def test_a_failed_connection_leaves_the_line_alone(window):
    ui = window('en')
    finish(ui, 'connect', connect_result(BODY.key))
    finish(ui, 'connect', error='No normal USB identity', error_type='ValueError')
    assert ui.build_label.text() == BODY_LABEL


def test_unknown_build_disables_write_buttons(window):
    ui = window('en')
    ui.look_editor.add_row(3)   # the look page's own rule then allows its button
    buttons = write_buttons(ui)
    assert {'action_setup_all', 'one_click_restore', 'action_direct_factory_reset', 'action_restore',
            'action_direct_fl23_enable', 'action_direct_fl23_disable', 'action_direct_looks_import',
            'action_vertical_enable', 'action_vertical_disable', 'action_sound_on', 'action_sound_off',
            'action_sound_audition', 'action_sound_install', 'action_sound_restore_sound'} <= {b.objectName() for b in buttons}
    assert enabled(buttons) == sorted(b.objectName() for b in buttons)
    finish(ui, 'connect', connect_result(None))
    assert enabled(buttons) == []


def test_the_look_pages_own_rules_never_re_enable_a_gated_button(window):
    ui = window('en')
    finish(ui, 'connect', connect_result(None))
    ui.look_editor.add_row(3)
    ui.look_editor.add_row(4)
    assert not ui.look_button.isEnabled()


def test_read_only_buttons_stay_enabled_on_an_unknown_build(window):
    ui = window('en')
    finish(ui, 'connect', connect_result(None))
    for name in ('action_connect', 'action_driver_scan', 'action_usb_stability', 'action_backup_inspect',
                 'action_sound_import', 'action_recipe_plan', 'action_direct_verify', 'action_sound_verify'):
        assert ui.findChild(W.QPushButton, name).isEnabled(), name


def start_everything_enabled(ui):
    """Click every enabled action button with launch mocked: the camera actions the window would start."""
    with patch.object(ui, 'launch') as launch:
        for button in ui.findChildren(W.QPushButton):
            if button.isEnabled() and (button.objectName().startswith('action_') or button.objectName() == 'one_click_restore'):
                button.click()
    return {call.args[0] for call in launch.call_args_list}


def test_no_enabled_button_can_start_a_write_on_an_unknown_build(window):
    ui = window('en')
    ui.look_editor.add_row(3)
    assert start_everything_enabled(ui) & jobs.POWER_ACTIONS   # the sweep does reach the write buttons
    finish(ui, 'connect', connect_result(None))
    started = start_everything_enabled(ui)
    assert {'connect', 'driver_scan', 'usb_stability'} <= started
    assert started & jobs.POWER_ACTIONS == set()


def test_a_supported_camera_enables_the_write_buttons_again(window):
    ui = window('en')
    ui.look_editor.add_row(3)
    buttons = write_buttons(ui)
    finish(ui, 'connect', connect_result(None))
    assert enabled(buttons) == []
    finish(ui, 'connect', connect_result(BODY.key))
    assert enabled(buttons) == sorted(b.objectName() for b in buttons)


def test_the_gate_holds_without_the_look_pages_own_refresh(window):
    # finished() re-enables every button, then gates them itself; it must not rely on the look page.
    ui = window('en')
    with patch.object(ui, 'refresh_look_controls'):
        finish(ui, 'connect', connect_result(None))
    assert enabled(write_buttons(ui)) == []


def test_a_later_job_does_not_re_enable_the_gated_buttons(window):
    ui = window('en')
    finish(ui, 'connect', connect_result(None))
    finish(ui, 'driver_scan', dict(devices=[]))
    assert enabled(write_buttons(ui)) == []
    assert ui.findChild(W.QPushButton, 'action_connect').isEnabled()


def test_an_unsupported_connection_is_explained_on_every_page(window):
    ui = window('en')
    finish(ui, 'connect', connect_result(None))
    assert ui.status.text() == UNSUPPORTED_LABEL
    assert ui.status_area.banner.kind == 'warning'
    finish(ui, 'connect', connect_result(PUBLIC.key))
    assert ui.status.text() != UNSUPPORTED_LABEL


def test_connection_test_help_says_it_reads_the_build(window):
    ui = window('en')
    help_text = 'Connects, reads the firmware build, then disconnects. Nothing is written.'
    assert help_text in {label.text() for label in ui.findChildren(W.QLabel)}
    assert STRINGS['连接后读取固件版本，然后断开，不写入任何内容。'] == help_text


# The connect worker ----------------------------------------------------------------------------

def run_connect(camera, tmp_path):
    with patch.object(devicesession, 'Camera', lambda *args, **kwargs: camera):
        return worker.run('connect', {}, tmp_path)


def assert_only_reads(camera):
    assert camera.link.writes() == []
    assert [call for call in camera.link.calls if call[0] != 'read'] == []
    assert [call[1] for call in camera.link.calls] == [AP, CP]


@pytest.mark.parametrize('build', BUILDS, ids=lambda build: build.key)
def test_connect_returns_the_identified_builds_key(build, tmp_path):
    camera = GateCamera(dict(UNKNOWN))
    with patch.object(buildprofile, 'identify', return_value=build) as identify:
        result = run_connect(camera, tmp_path)
    assert result == connect_result(build.key)
    identify.assert_called_once_with(UNKNOWN[AP], UNKNOWN[CP])
    assert camera.firmware_build is build
    assert_only_reads(camera)
    json.dumps(result)


def test_connect_on_an_unsupported_camera_returns_none_and_does_not_raise(tmp_path):
    camera = GateCamera(dict(UNKNOWN))
    result = run_connect(camera, tmp_path)
    assert result == connect_result(None)
    assert camera.firmware_build is None
    assert_only_reads(camera)


def test_connect_logs_the_refusal_with_the_digests(tmp_path, capsys):
    run_connect(GateCamera(dict(UNKNOWN)), tmp_path)
    printed = capsys.readouterr().out
    assert buildprofile.unsupported_digests(
        next(line for line in printed.splitlines() if line.startswith('此相机的固件版本不受支持'))) is not None


def test_an_unsupported_camera_still_refuses_every_write_after_connect(tmp_path):
    camera = GateCamera(dict(UNKNOWN))
    run_connect(camera, tmp_path)
    with pytest.raises(UnsupportedFirmware):
        camera.property_write(0x02cf0001, b'\0', {0x02cf0001})


@pytest.mark.parametrize('fixture, key', [('public', PUBLIC.key), ('body', BODY.key), ('hybrid', None)])
def test_connect_identifies_the_real_firmware(build_fixtures, fixture, key, tmp_path):
    programs = getattr(build_fixtures, fixture)
    camera = GateCamera({AP: programs.ap, CP: programs.cp})
    assert run_connect(camera, tmp_path) == connect_result(key)
    assert_only_reads(camera)


# A job a firmware refusal stopped -------------------------------------------------------------------

def refusal_message():
    """What the gate says for the stand-in programs of test_checkpoint.values() (40 kB of zeros each)."""
    with pytest.raises(UnsupportedFirmware) as error:
        buildprofile.identify(bytes(40000), bytes(40000))
    return str(error.value)


def english(message):
    return "This camera's firmware build isn't supported. Nothing was written. (appFw.so %s…, cpapp-b.bin %s…)" % \
        buildprofile.unsupported_digests(message)


def refused_one_click(folder):
    """A one-click job the gate refused at the first camera step after the drivers, as allinone leaves it."""
    from desktopapp import allinone
    message = refusal_message()

    def dispatch(action, arguments, step):
        if action == 'usb_prepare':
            return {'ok': True}
        raise UnsupportedFirmware(message)
    arguments = dict(workspace=str(folder), firmware='2.01', power_confirmed=True,
                     options=dict(fl23=True, sound=True, vertical=True, plugin=False, looks=[]))
    with pytest.raises(UnsupportedFirmware):
        allinone.run(arguments, dispatch=dispatch)
    state = json.loads((folder / 'setup.private.json').read_text(encoding='utf-8'))
    assert state['phase'] == 'NEEDS_REVIEW' and state['error'] == message
    return folder


def refused_direct(folder, mode, **arguments):
    """A DirectJob the gate refused: the engine runs on a camera whose programs are of no supported
    build and leaves its state on disk. Nothing reaches the camera."""
    from test_checkpoint import Camera, fake_compile, values
    from test_direct import SimDirect
    camera = Camera(values())
    camera.carries = None
    job = SimDirect(folder, factory=camera)
    with patch.object(Camera, '__call__', lambda obj, expected=None: obj), \
            patch.object(checkpointworker, 'compile_worker', side_effect=fake_compile), \
            pytest.raises(UnsupportedFirmware) as error:
        job.run_direct(mode, version='2.01', power_confirmed=True, **arguments)
    state = json.loads((folder / 'direct.private.json').read_text(encoding='utf-8'))
    assert state['phase'] == 'NEEDS_REVIEW' and state['error'] == str(error.value)
    assert camera.saves == [] and camera.native_calls == []
    return folder


@pytest.fixture
def refused(tmp_path):
    """The three kinds of job a firmware refusal stops, each in its own folder: {kind: folder}."""
    return dict(
        setup=refused_one_click(tmp_path / 'setup'),
        factory=refused_direct(tmp_path / 'factory', 'factory_reset', factory_values={}, factory_path='builtin'),
        look=refused_direct(tmp_path / 'look', 'slot_default', slot=1))


SETTINGS = dict(setup='setup_work', factory='factory_direct_work', look='look_direct_work')
CONTINUE = ('继续安装', '继续恢复／核对未完成事务', '继续槽位更改', '重试本次更改（上次未写入）', '查看未完成任务记录')


def offered(ui):
    """The buttons that continue, resume or retry a stopped job, enabled and not hidden."""
    labels = {i18n.tr(key) for key in CONTINUE}
    return sorted(button.text() for button in ui.findChildren(W.QPushButton)
                  if button.text() in labels and button.isEnabled() and not button.isHidden())


def point_at(ui, refused):
    ui.settings.update({SETTINGS[kind]: str(folder) for kind, folder in refused.items()})
    ui.fields['factory_failed_work'].setText(str(refused['factory']))


def reopened(window, refused, **extra):
    """The app opened again with the pages pointing at the stopped jobs."""
    write_json(data_root() / 'desktop.json', dict(language='en', **{SETTINGS[k]: str(v) for k, v in refused.items()}, **extra))
    return window()


def stopped_texts(ui):
    return (ui.setup_note.text(), ui.factory_status.text(), ui.look_pending.text())


def message_of(refused):
    return json.loads((refused['look'] / 'direct.private.json').read_text(encoding='utf-8'))['error']


@pytest.mark.parametrize('action', ['setup_all', 'direct_factory_reset', 'direct_looks_import'])
def test_after_a_refusal_no_page_offers_resume_and_the_banner_says_why(window, refused, action):
    ui = window('en')
    point_at(ui, refused)
    message = message_of(refused)
    finish(ui, action, error=message, error_type='UnsupportedFirmware')
    assert ui.status.text() == 'Operation stopped: ' + english(message) + '. Please export diagnostics.'
    assert ui.status_area.banner.kind == 'danger'
    assert offered(ui) == []
    assert ui.build_label.text() == UNSUPPORTED_LABEL
    assert enabled(write_buttons(ui)) == []
    assert stopped_texts(ui) == (english(message),) * 3


def test_a_refused_one_click_job_is_replaced_by_the_refusal_message(window, refused):
    ui = window('en')
    point_at(ui, refused)
    message = message_of(refused)
    finish(ui, 'setup_all', error=message, error_type='UnsupportedFirmware')
    assert ui.setup_button.text() == 'One-Click Install'
    assert not ui.setup_note.isHidden() and ui.setup_note.text() == english(message)
    assert ui.setup_presets.isEnabled() and ui.setup_fl23.isEnabled()
    assert not ui.setup_result_button.isVisible()


def test_a_refused_factory_job_shows_the_refusal_not_an_unfinished_transaction(window, refused):
    ui = window('en')
    point_at(ui, refused)
    message = message_of(refused)
    finish(ui, 'direct_factory_reset', error=message, error_type='UnsupportedFirmware')
    assert ui.factory_status.text() == english(message)
    assert ui.factory_button.text() == i18n.tr('恢复／继续恢复原厂 2.01 功能（无需旧备份）')


def test_a_refused_look_job_keeps_the_list_editable_and_shows_the_refusal(window, refused):
    ui = window('en')
    ui.look_editor.add_row(3)
    point_at(ui, refused)
    message = message_of(refused)
    finish(ui, 'direct_looks_import', error=message, error_type='UnsupportedFirmware')
    assert ui.look_editor.isEnabled()
    assert ui.look_editor.values() == [dict(slot=3, action='restore')]
    assert not ui.look_pending.isHidden() and ui.look_pending.text() == english(message)
    assert ui.look_button.text() == i18n.tr('查看并应用这 %d 项更改') % 1


def test_after_a_restart_no_page_offers_to_continue_a_refused_job(window, refused):
    ui = reopened(window, refused)
    message = message_of(refused)
    assert offered(ui) == []
    assert stopped_texts(ui) == (english(message),) * 3
    assert not ui.setup_note.isHidden() and not ui.look_pending.isHidden()
    # The build is not known until a connection test: nothing is disabled on a stale job's account.
    assert ui.build_label.text() == NOT_CHECKED
    assert enabled(write_buttons(ui)) == sorted(b.objectName() for b in write_buttons(ui)
                                                if b.objectName() != 'action_direct_looks_import')


def test_a_new_one_click_job_starts_instead_of_the_refused_one(window, refused):
    ui = reopened(window, refused)
    arguments = ui.setup_args()
    assert arguments['workspace'] != str(refused['setup'])
    assert not Path(arguments['workspace'], 'setup.private.json').exists()


def test_a_new_look_job_starts_instead_of_the_refused_one(window, refused):
    ui = reopened(window, refused)
    row = ui.look_editor.add_row(3)
    row.action.setCurrentIndex(0)
    with patch('desktopapp.window.ask', return_value=True), patch.object(ui, 'launch') as launch:
        ui.look_button.click()
    launch.assert_called_once()
    assert launch.call_args.args[0] == 'direct_looks_import'
    assert 'failed_workspace' not in launch.call_args.args[1]


def test_the_refusal_is_plain_chinese_in_the_chinese_interface(window, refused):
    write_json(data_root() / 'desktop.json', dict(language='zh_CN', **{SETTINGS[k]: str(v) for k, v in refused.items()}))
    ui = window()
    message = message_of(refused)
    assert stopped_texts(ui) == (message,) * 3
    assert offered(ui) == []


@pytest.mark.parametrize('error', ['USB unavailable before reads', buildprofile.JOB_OTHER_BUILD % ('public-2.01', 'body-2.01-20250923'),
                                   buildprofile.UNSUPPORTED % ('XYZ', 'f5a477588698ef96')],
                         ids=['another error', 'another build, not an unsupported one', 'a message that only looks like it'])
def test_a_job_stopped_for_any_other_reason_still_offers_to_continue(window, refused, error):
    for folder, name in ((refused['setup'], 'setup.private.json'), (refused['factory'], 'direct.private.json'),
                         (refused['look'], 'direct.private.json')):
        state = json.loads((folder / name).read_text(encoding='utf-8'))
        write_json(folder / name, dict(state, error=error))
    ui = reopened(window, refused)
    assert offered(ui) == sorted([i18n.tr('继续安装'), i18n.tr('继续恢复／核对未完成事务'),
                                  i18n.tr('重试本次更改（上次未写入）')])


def test_a_one_click_job_waiting_for_the_restart_keeps_its_continue_button(window, refused):
    # Only a job the refusal put in NEEDS_REVIEW is dropped. One waiting for the restart (allinone keeps
    # that phase when its verify step fails) still has the verify to do.
    state_path = refused['setup'] / 'setup.private.json'
    state = json.loads(state_path.read_text(encoding='utf-8'))
    write_json(state_path, dict(state, phase='WAIT_RELOAD'))
    ui = reopened(window, refused)
    assert ui.setup_button.text() == 'Continue Installation'


def test_unidentified_refusal_is_treated_the_same(window, refused):
    for folder, name in ((refused['setup'], 'setup.private.json'), (refused['factory'], 'direct.private.json'),
                         (refused['look'], 'direct.private.json')):
        state = json.loads((folder / name).read_text(encoding='utf-8'))
        write_json(folder / name, dict(state, error=devicesession.UNIDENTIFIED))
    ui = reopened(window, refused)
    assert offered(ui) == []
    assert stopped_texts(ui) == (STRINGS[devicesession.UNIDENTIFIED],) * 3
