"""A firmware-build refusal keeps its type from where the gate raises it to the window (R60).

The worker records an exception's class name as the job's error_type, and a stopped job's own state
records it too. The window decides from that type, never from the message text, that a job was refused
before anything was written: it marks the build unsupported for an UnsupportedFirmware and offers no
"Continue" for a refused job. No camera: the sound jobs run the real worker, sound CLI and gate over an
in-memory link (test_firmware_gate).
"""
import json
from pathlib import Path
import sys
from unittest.mock import Mock, patch

import pytest
from PySide6 import QtWidgets as W

from desktopapp import i18n, jobs, worker
from desktopapp.engine_text import display
from desktopapp.paths import data_root, write_json
from looktool import buildprofile, checkpointworker, devicesession, direct

from guihelpers import HAN_OR_PUNCTUATION, finish_failed_job, stopped_banner  # noqa: E402
from test_build_label import UNSUPPORTED_LABEL, enabled, english, write_buttons  # noqa: E402
from test_firmware_gate import AP, CP, UNKNOWN, SoundGateCamera, refusal  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'src/shutter_sound'))
import boot_trial  # noqa: E402
import sound_cli  # noqa: E402
import trial  # noqa: E402

UNKNOWN_WRITE = 'do not repeat unknown writes'


def every_subclass(cls):
    for sub in cls.__subclasses__():
        yield sub
        yield from every_subclass(sub)


def test_the_refusal_types_are_every_refusal_class():
    # direct is imported above: its JobOtherBuild is a refusal and a ContentChanged.
    assert buildprofile.REFUSAL_TYPES == {cls.__name__ for cls in every_subclass(buildprofile.Refusal)}
    assert issubclass(direct.JobOtherBuild, direct.ContentChanged)


def test_a_refusal_carries_what_it_names():
    with pytest.raises(buildprofile.UnsupportedFirmware) as error:
        buildprofile.identify(UNKNOWN[AP], UNKNOWN[CP])
    assert str(error.value) == refusal(UNKNOWN) == buildprofile.UNSUPPORTED % error.value.digests
    other = buildprofile.OtherBuild(buildprofile.REFERENCE_OTHER_BUILD, 'public-2.01', 'body-2.01-20250923')
    assert other.builds == ('public-2.01', 'body-2.01-20250923')
    assert str(other) == buildprofile.REFERENCE_OTHER_BUILD % other.builds
    none = buildprofile.OtherBuild(buildprofile.SAVED_UNIDENTIFIED)
    assert none.builds == () and str(none) == buildprofile.SAVED_UNIDENTIFIED
    job = direct.JobOtherBuild(buildprofile.JOB_OTHER_BUILD, 'body-2.01-20250923', 'public-2.01')
    assert (job.recorded, job.camera) == ('body-2.01-20250923', 'public-2.01')
    assert str(job) == buildprofile.JOB_OTHER_BUILD % ('body-2.01-20250923', 'public-2.01')


@pytest.mark.parametrize('refused, kind', [(buildprofile.SAVED_OTHER_BUILD, buildprofile.OtherBuild),
                                           (buildprofile.JOB_OTHER_BUILD, direct.JobOtherBuild)])
def test_same_build_refuses_another_key_with_the_kind_asked_for(refused, kind):
    buildprofile.same_build('public-2.01', 'public-2.01', refused, kind)
    with pytest.raises(kind) as error:
        buildprofile.same_build('public-2.01', 'body-2.01-20250923', refused, kind)
    assert type(error.value) is kind
    assert error.value.builds == ('public-2.01', 'body-2.01-20250923')


# The two shutter-sound jobs that write through the sound CLI ------------------------------------------

def sound_job(tmp_path, monkeypatch, action):
    """Run `action` through the real worker.execute_request, the sound CLI and the gate, on a camera
    whose programs are of no supported build. Returns the job folder."""
    workspace = tmp_path / 'sound'
    clip = workspace / 'jobs/converted'
    clip.mkdir(parents=True)
    (clip / 'custom-native.private.bin').write_bytes(b'\1' * 64)
    (workspace / 'conversion.private.json').write_text(json.dumps({'conversion': str(clip)}), encoding='utf-8')
    # The camera the sound CLI opens; its programs reach the real Camera.identify_programs in trial.capture.
    monkeypatch.setattr(trial, 'factory', lambda expected=None: SoundGateCamera(dict(UNKNOWN)))
    monkeypatch.setattr(boot_trial, 'require_dependencies', lambda: None)
    monkeypatch.setattr('desktopapp.platforms.macos_authorization.required', lambda action: False)
    job = tmp_path / 'job'
    job.mkdir()
    request = tmp_path / 'request.private.json'
    request.write_text(json.dumps(dict(action=action, job_dir=str(job), arguments=dict(
        workspace=str(workspace), backup=str(tmp_path / 'backup'), power_confirmed=True))), encoding='utf-8')
    assert worker.execute_request(request) == 2
    return job


@pytest.mark.parametrize('action', ['sound_install', 'sound_audition'])
def test_a_sound_refusal_reaches_the_status_with_its_type(tmp_path, monkeypatch, action):
    job = sound_job(tmp_path, monkeypatch, action)
    status = json.loads((job / 'status.private.json').read_text(encoding='utf-8'))
    assert status['error_type'] == 'UnsupportedFirmware'
    assert status['error'] == refusal(UNKNOWN)  # the gate's own message, without an unknown-write warning
    log = (job / 'worker.log').read_text(encoding='utf-8')
    assert 'Stopped: ' + refusal(UNKNOWN) + '\n' in log and UNKNOWN_WRITE not in log


@pytest.mark.parametrize('action', ['sound_install', 'sound_audition'])
def test_a_sound_refusal_marks_the_build_unsupported_and_disables_writes(tmp_path, monkeypatch, window, action):
    job = sound_job(tmp_path, monkeypatch, action)
    ui = window('en')
    assert enabled(write_buttons(ui)) != []
    ui.current_job = job
    ui.process = Mock()
    ui.finished(2, None)
    assert ui.build_label.text() == UNSUPPORTED_LABEL and ui.build_unsupported
    assert enabled(write_buttons(ui)) == []
    assert ui.status.text() == stopped_banner(english(refusal(UNKNOWN)))
    assert not HAN_OR_PUNCTUATION.search(ui.status.text())


def test_the_sound_cli_warns_of_unknown_writes_only_for_other_errors(tmp_path, monkeypatch, capsys):
    stopped = []
    for raised in (buildprofile.UnsupportedFirmware(refusal(UNKNOWN)), ValueError('USB pipe error')):
        def command(args, raised=raised):
            raise raised
        monkeypatch.setattr(sound_cli, 'workspace_command', command)
        assert sound_cli.main(['install', '--workspace', str(tmp_path), '--power-confirmed'],
                              failure=lambda exc, message: stopped.append((exc, message))) == 2
    printed = capsys.readouterr().err
    assert stopped[0] == (stopped[0][0], refusal(UNKNOWN)) and isinstance(stopped[0][0], buildprofile.UnsupportedFirmware)
    assert stopped[1][1] == 'USB pipe error\nKeep the workspace and backup; do not repeat unknown writes.'
    assert printed.count(UNKNOWN_WRITE) == 1


def test_an_offline_sound_command_never_loads_the_gate(monkeypatch):
    # import and volume run without looktool: telling a refusal apart must not import it.
    monkeypatch.delitem(sys.modules, 'looktool.buildprofile')
    assert not sound_cli.build_refusal(ValueError('the clip is silent'))
    assert 'looktool.buildprofile' not in sys.modules


# Factory restore after a reference of the other build ------------------------------------------------

def other_build_factory_job(folder):
    """What the real engine leaves on disk when Factory restore is given a full Sony reference of the
    public build (the only BODYDATA.DAT Sony publishes) on a camera of the body build: refused before
    anything is planned or written."""
    from test_checkpoint import Camera, fake_compile, values
    from test_direct import SimDirect
    _, body = buildprofile.BUILDS
    camera = Camera(values())
    camera.carries = body
    job = SimDirect(folder, factory=camera)
    reference = {'firmware_build': buildprofile.BUILDS[0].key}
    with patch.object(Camera, '__call__', lambda obj, expected=None: obj), \
            patch.object(checkpointworker, 'compile_worker', side_effect=fake_compile), \
            pytest.raises(buildprofile.OtherBuild) as error:
        job.run_direct('factory_reset', version='2.01', power_confirmed=True, factory_values=reference,
                       factory_path=str(folder / 'factory-2.01'))
    assert camera.saves == [] and camera.native_calls == []
    return str(error.value)


def test_a_reference_of_the_other_build_records_its_refusal_type(tmp_path):
    message = other_build_factory_job(tmp_path / 'factory')
    state = json.loads((tmp_path / 'factory/direct.private.json').read_text(encoding='utf-8'))
    assert (state['phase'], state['error'], state['error_type']) == ('NEEDS_REVIEW', message, 'OtherBuild')
    assert state['failed_during'] == 'READING'


@pytest.mark.parametrize('restarted', [False, True], ids=['after the job', 'after a restart'])
def test_the_factory_page_after_a_reference_of_the_other_build(window, tmp_path, restarted):
    folder = tmp_path / 'factory'
    message = other_build_factory_job(folder)
    if restarted:
        write_json(data_root() / 'desktop.json', dict(language='en', factory_direct_work=str(folder)))
        ui = window()
    else:
        ui = window('en')
        ui.settings['factory_direct_work'] = str(folder)
        ui.current_job = jobs.new_job('direct_factory_reset', {})
        write_json(ui.current_job / 'status.private.json', dict(
            phase='FAILED', action='direct_factory_reset', error=message, error_type='OtherBuild'))
        ui.process = Mock()
        ui.finished(2, None)
    # Nothing was written, and the page says why: no "Continue…" and no "Restore not finished".
    assert ui.factory_status.text() == display(message)
    assert 'Nothing was written.' in ui.factory_status.text() and 'not finished' not in ui.factory_status.text()
    assert ui.factory_button.text() == i18n.tr('恢复／继续恢复原厂 2.01 功能（无需旧备份）')
    assert not [button.text() for button in ui.findChildren(W.QPushButton) if button.text().startswith('Continue')]
    # The camera's build is a supported one: only the reference was of another build.
    assert not ui.build_unsupported


# A worker that quit without a status ---------------------------------------------------------------

@pytest.mark.parametrize('language, unknown, repeat', [
    ('zh_CN', '结果未知', '查看日志前不要重复此操作'),
    ('en', 'its result is unknown', 'Don’t repeat it until you’ve read the log')])
def test_a_crashed_worker_banner_says_the_result_is_unknown_in_both_languages(window, language, unknown, repeat):
    # CV5: the Chinese banner states the safety fact the English states.
    ui = window(language)
    ui.current_job = jobs.new_job('direct_fl23_enable', {})
    ui.process = Mock()
    ui.finished(-1, None)  # no status file: the worker quit before writing one
    assert unknown in ui.status.text() and repeat in ui.status.text()


# Every refusal in the banner ---------------------------------------------------------------------

PUBLIC_LABEL, BODY_LABEL = 'Sony 2.01 (public update)', 'Sony 2.01 (camera build, 23 Sep 2025)'
PUBLIC_KEY, BODY_KEY = (build.key for build in buildprofile.BUILDS)
REFUSALS = [
    (buildprofile.UNSUPPORTED % ('2ea02f7ecbc5bb91', 'f5a477588698ef96'), 'UnsupportedFirmware',
     "This camera's firmware build isn't supported. Nothing was written. (appFw.so 2ea02f7ecbc5bb91…, "
     "cpapp-b.bin f5a477588698ef96…)"),
    (devicesession.UNIDENTIFIED, 'UnsupportedFirmware',
     "This camera's firmware build hasn't been identified, so nothing was written."),
    (buildprofile.SAVED_OTHER_BUILD % (PUBLIC_KEY, BODY_KEY), 'OtherBuild',
     'The saved bytes come from %s, but the camera runs %s. Nothing was written.' % (PUBLIC_LABEL, BODY_LABEL)),
    (buildprofile.SAVED_UNIDENTIFIED, 'OtherBuild',
     "The firmware build of the saved bytes can't be identified, so nothing was written."),
    (buildprofile.REFERENCE_OTHER_BUILD % (PUBLIC_KEY, BODY_KEY), 'OtherBuild',
     'The chosen Sony firmware file is for %s, but the camera runs %s. Nothing was written.' % (PUBLIC_LABEL, BODY_LABEL)),
    (buildprofile.REFERENCE_UNSUPPORTED, 'OtherBuild',
     "The chosen Sony firmware file isn't a supported build, so nothing was written."),
    (buildprofile.JOB_OTHER_BUILD % (BODY_KEY, PUBLIC_KEY), 'JobOtherBuild',
     'This job was planned for %s, but the camera now runs %s. Nothing was verified or written.' % (BODY_LABEL, PUBLIC_LABEL)),
]


@pytest.mark.parametrize('error, error_type, english', REFUSALS, ids=[row[1] + '-' + str(i) for i, row in enumerate(REFUSALS)])
def test_every_refusal_reads_in_english_with_build_labels(window, error, error_type, english):
    # M6: the English names builds by their labels, as the Connection page does, never by raw keys.
    text = finish_failed_job(window(language='en'), error, error_type=error_type)
    assert text == stopped_banner(english)
    assert not HAN_OR_PUNCTUATION.search(text) and PUBLIC_KEY not in text and BODY_KEY not in text


@pytest.mark.parametrize('error, error_type, english', REFUSALS, ids=[row[1] + '-' + str(i) for i, row in enumerate(REFUSALS)])
def test_every_refusal_stays_verbatim_in_chinese(window, error, error_type, english):
    stop = '' if error.endswith('。') else '。'  # a refusal that ends its sentence gets no second full stop
    assert finish_failed_job(window(), error, error_type=error_type) == '操作停止：' + error + stop + '请导出诊断包。'


def test_the_chinese_sources_name_the_build_as_a_build():
    # M6: 固件编译版本 (the firmware's compiled build) where the build is meant, not 固件版本 (its version).
    sources = [buildprofile.UNSUPPORTED, buildprofile.SAVED_OTHER_BUILD, buildprofile.SAVED_UNIDENTIFIED,
               buildprofile.REFERENCE_OTHER_BUILD, buildprofile.REFERENCE_UNSUPPORTED, buildprofile.JOB_OTHER_BUILD,
               devicesession.UNIDENTIFIED, boot_trial.RETIRED_UNKNOWN_BUILD]
    assert all('固件编译版本' in text and '固件版本' not in text for text in sources)
    from desktopapp.en import STRINGS
    assert STRINGS['相机固件编译版本'] == 'Camera firmware build'


def test_capturing_the_camera_never_overwrites_the_build_a_job_recorded(tmp_path):
    # L209: verify reads the job's recorded build first; capture keeps it and fills it in only when absent.
    from test_checkpoint import Camera, values
    from test_direct import SimDirect
    camera = Camera(values())    # plays the public build
    job = SimDirect(tmp_path / 'job', factory=camera)
    job.state = {'firmware_build': 'body-2.01-20250923'}
    job.capture(camera)
    assert job.state['firmware_build'] == 'body-2.01-20250923'
    job.state = {}
    job.capture(camera)
    assert job.state['firmware_build'] == buildprofile.BUILDS[0].key
