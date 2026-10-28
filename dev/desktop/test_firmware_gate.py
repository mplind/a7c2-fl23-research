"""No camera write of any kind happens until the programs read from the camera are a supported build.

The cameras here are the production session classes over an in-memory service link, so every
gate under test is the real one. Test-only constructs: Link, Core, and simbuild.identified where a
test needs small stand-in programs to play Sony's public 2.01.
"""
import ast
import copy
import hashlib
import json
import posixpath
from pathlib import Path
import sys
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest
from PySide6 import QtWidgets as W

from desktopapp import jobs, worker
from desktopapp.paths import write_json
from looktool import (buildprofile, checkpointjob, checkpointworker, devicejob, devicesession, direct,
                      namespause, nameworker, portraitjob, runtimebindings)
from looktool.buildprofile import UnsupportedFirmware

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'src/shutter_sound'), str(ROOT / 'src/vertical')]
import boot_trial  # noqa: E402
import buffer_trial  # noqa: E402
import candidate  # noqa: E402
import trial  # noqa: E402
from verticaltool import device as vertical, portraitstage  # noqa: E402

from guihelpers import HAN  # noqa: E402
from simbuild import PUBLIC, identified as identified_as  # noqa: E402

AP, CP = '/usr/lib/appFw.so', '/cp/cpapp-b.bin'
BODY = dict(model='ILCE-7CM2', serial_sha256='test-body')
UNKNOWN = {AP: bytes(40000), CP: b'\1' * 40000}
WRITES = ('jiritsu16', 'jiritsu18', 'writeBackup', 'saveBackup', 'cp_write')


def refusal(programs):
    """The message identify_programs gives for programs of no supported build."""
    ap, cp = (hashlib.sha256(programs[path]).hexdigest()[:16] for path in (AP, CP))
    return buildprofile.UNSUPPORTED % (ap, cp)


class Link:
    """The service link in memory: files by absolute path, and every command in order.

    Writing libJit.so is the launch; `launch(files)` stands in for the worker running."""
    def __init__(self, files, launch=None):
        self.files, self.launch = dict(files), launch
        self.calls, self.selected, self.healthy = [], None, True
        self.camera = SimpleNamespace(writeBackup=self.writeBackup, saveBackup=self.saveBackup,
                                      readBackup=self.readBackup, getBackupPresetData=self.getBackupPresetData)

    def writes(self):
        return [call for call in self.calls if call[0] in WRITES]

    def select(self, path):
        self.calls.append(('select', path))
        self.selected = path

    def jiritsu(self, command, data=b'', missing=False):
        self.calls.append(('jiritsu%d' % command, self.selected))
        if command == 16:
            self.files[self.selected] = data[3:]
            if self.selected.endswith('/libJit.so') and self.launch:
                self.launch(self.files)
        elif command == 18:
            self.files.pop(self.selected, None)

    def read(self, path, missing=False):
        path = posixpath.normpath(path)
        self.calls.append(('read', path))
        if path in self.files:
            return self.files[path]
        if missing:
            return None
        raise FileNotFoundError(path)

    def call(self, method, *args):
        return method(*args)

    def writeBackup(self, key, value):
        self.calls.append(('writeBackup', key))

    def saveBackup(self, group):
        self.calls.append(('saveBackup', group))

    def readBackup(self, key):
        self.calls.append(('readBackup', key))
        return b'\0'

    def getBackupPresetData(self, memory):
        self.calls.append(('getBackupPresetData', memory))
        return b'settings'

    def cp_write(self, key, data):
        self.calls.append(('cp_write', key))


class Core:
    MODEL = 'ILCE-7CM2'

    def parse_native(self, name, raw, mode=None):
        return dict(native=name, image_mode='0', spans=[], boot_id='boot')

    def assets(self):
        return {'files': {}}


class Offline:
    """A production session class over Link instead of USB: programs pinned, never identified."""
    def __init__(self, files=None, launch=None):
        devicesession.Camera.__init__(self)
        self.link = Link(UNKNOWN if files is None else files, launch)
        self.core, self.identity = Core(), dict(BODY)
        self.service_only, self.programs_pinned = False, True

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class GateCamera(Offline, devicesession.Camera):
    pass


class CheckpointGateCamera(Offline, checkpointjob.CheckpointCamera):
    pass


class SoundGateCamera(Offline, type(trial.factory())):
    pass


def unidentified(cls):
    return cls()


def unknown_build(cls):
    camera = cls()
    with pytest.raises(UnsupportedFirmware):
        camera.identify_programs(camera.read(AP), camera.read(CP))
    camera.link.calls.clear()
    return camera


def identified(cls):
    camera = identified_as(cls())
    assert camera.firmware_build is PUBLIC
    return camera


def worker_file(folder):
    path = Path(folder) / 'worker.so'
    path.write_bytes(b'\x7fELF test worker')
    return path


def journal():
    return SimpleNamespace(record=lambda *args, **kwargs: None, raw=lambda *args: None, report={})


def rollback(kind, mode):
    def run(camera, folder):
        job = checkpointjob.Rollback(folder / 'job')
        job.root.mkdir()
        job.state = {}
        return job.native(camera, kind, mode, {'path': str(worker_file(folder))})
    return CheckpointGateCamera, run


def direct_names(mode):
    def run(camera, folder):
        job = direct.DirectJob(folder / 'job')
        job.root.mkdir()
        job.state = {}
        return job.forward_names(camera, {'path': str(worker_file(folder)), 'unchanged': False}, mode)
    return GateCamera, run


def lut_job(kind, mode):
    def run(camera, folder):
        job = devicejob.Job(folder / 'job')
        job.hash_checks = False
        job.state = {'journal': [], 'program_build': {'unchanged': False, 'contract': {}},
                     'name_build': {'unchanged': False}}
        for name in ('program/program.so', 'names/names.so'):
            path = job.root / 'worker' / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b'\x7fELF test worker')
        return job._invoke(camera, kind, mode)
    return GateCamera, run


def look_bindings(camera, folder):
    selected = [dict(key=0x02cf0cd0, index=10, value=0)]
    owner = SimpleNamespace(root=folder, zig=None, state={'journal': []}, _runtime_binding_ap=b'ap',
                            record=lambda *args, **kwargs: None, raw=lambda *args: None)
    with patch.object(runtimebindings, 'targets', return_value=selected), \
         patch.object(runtimebindings, 'build', return_value={'path': str(worker_file(folder)), 'targets': selected}):
        return runtimebindings.sync(camera, owner, {0x02cf0cd0: b'\0'})


def sound_native(kind, mode):
    def run(camera, folder):
        return trial.run_native(camera, folder, {'journal': []}, worker_file(folder), kind, mode,
                                {'windows': 1, 'sizes': [1, 1]})
    return SoundGateCamera, run


def sound_files(mode):
    def run(camera, folder):
        return boot_trial.invoke_files(camera, folder, {'journal': []}, worker_file(folder), mode)
    return SoundGateCamera, run


def vertical_worker(method, value):
    def run(camera, folder):
        return getattr(vertical.Workers(camera, journal()), method)(value)
    return GateCamera, run


def portrait(mode):
    def run(camera, folder):
        stage = object.__new__(portraitstage.Stage)
        stage.camera, stage.owner = camera, SimpleNamespace(record=lambda *a, **k: None, raw=lambda *a: None)
        stage.build = {'path': str(worker_file(folder))}
        return stage.invoke(mode)
    return GateCamera, run


# Every primitive with a persistent effect on the camera, and every launcher that reaches one.
PRIMITIVES = {
    'property_write': (GateCamera, lambda camera, folder: camera.property_write(0x02cf0001, b'\0', {0x02cf0001})),
    'save_settings-AP': (GateCamera, lambda camera, folder: camera.save_settings()),
    'save_settings-CP': (GateCamera, lambda camera, folder: camera.save_settings(0x02a4)),
    'cp_write': (GateCamera, lambda camera, folder: camera.cp_write(0x02a40001, bytes(8192))),
    **{'Rollback.native-%s-%d' % km: rollback(*km)
       for km in (('program', 0), ('program', 1), ('names', 2), ('names', 4), ('purge', 5), ('wbi', 0),
                  ('wbi', 1), ('runtime', 1))},
    **{'DirectJob.forward_names-%d' % mode: direct_names(mode) for mode in (0, 1, 3)},
    **{'devicejob.Job._invoke-%s-%d' % km: lut_job(*km)
       for km in (('program', 0), ('program', 1), ('program', 2), ('names', 0), ('names', 1),
                  ('names', 2), ('names', 3), ('wbi', 1))},
    'runtimebindings.sync': (GateCamera, look_bindings),
    **{'trial.run_native-%s-%d' % km: sound_native(*km)
       for km in (('program', 0), ('program', 1), ('wbi', 0), ('wbi', 1))},
    **{'boot_trial.invoke_files-%d' % mode: sound_files(mode) for mode in (0, 1, 2)},
    **{'vertical.Workers.%s-%d' % mv: vertical_worker(*mv)
       for mv in (('ram', 0), ('ram', 1), ('aliases', 0), ('aliases', 1), ('aliases', 2))},
    **{'portraitstage.Stage.invoke-%d' % mode: portrait(mode) for mode in (1, 2, 3)},
}


@pytest.mark.parametrize('primitive', PRIMITIVES)
def test_unknown_build_refuses_every_write_primitive(primitive, tmp_path):
    cls, run = PRIMITIVES[primitive]
    camera = unknown_build(cls)
    with pytest.raises(UnsupportedFirmware, match=devicesession.UNIDENTIFIED):
        run(camera, tmp_path)
    assert camera.link.writes() == []


@pytest.mark.parametrize('primitive', PRIMITIVES)
def test_write_before_programs_are_read_is_refused(primitive, tmp_path):
    cls, run = PRIMITIVES[primitive]
    camera = unidentified(cls)
    with pytest.raises(UnsupportedFirmware, match=devicesession.UNIDENTIFIED):
        run(camera, tmp_path)
    assert camera.link.writes() == [] and camera.firmware_build is None


@pytest.mark.parametrize('primitive', PRIMITIVES)
def test_an_identified_build_lets_each_primitive_reach_the_camera(primitive, tmp_path):
    """The refusals above come from the gate: identified, each primitive writes to the link."""
    cls, run = PRIMITIVES[primitive]
    camera = identified(cls)
    try:
        run(camera, tmp_path)
    except UnsupportedFirmware:
        raise
    except Exception:  # the in-memory link runs no worker; only the first write matters here
        pass
    assert camera.link.writes()


def test_native_launch_refusal_precedes_any_link_traffic(tmp_path):
    camera = unidentified(GateCamera)
    with pytest.raises(UnsupportedFirmware):
        devicesession.invoke(camera, b'worker', kind='program', stage='lut-program-staged.so',
                             request='a7c2.install.request', result='a7c2.install.result', contents=b'request',
                             mode=1, decode=dict, record=lambda *a, **k: None, save_raw=lambda raw: None)
    assert camera.link.calls == []


def test_read_only_allowlist_is_exactly_the_reviewed_launches():
    assert devicesession.READ_ONLY_NATIVE == frozenset({('runtime', 0), ('probe', 0)})


@pytest.mark.parametrize('kind,mode,staged_request', [
    ('runtime', 1, None), ('probe', 1, None), ('runtime', 0, 'a7c2.wbi.request'),
    ('probe', 0, 'a7c2.install.request'), ('audition', 0, None), ('bindings', 1, None)])
def test_any_launch_outside_the_allowlist_needs_the_build(kind, mode, staged_request):
    """A read-only label never covers a launch that stages a request, or another mode."""
    camera = unidentified(GateCamera)
    with pytest.raises(UnsupportedFirmware):
        devicesession.invoke(camera, b'worker', kind=kind, stage='lut-runtime-staged.so', request=staged_request,
                             result='a7c2.runtime.result', contents=b'request' if staged_request else None, mode=mode,
                             decode=dict, record=lambda *a, **k: None, save_raw=lambda raw: None)
    assert camera.link.calls == []


def test_programs_of_the_right_size_but_no_known_build_are_refused():
    programs = {AP: bytes(PUBLIC.ap_bytes), CP: bytes(PUBLIC.cp_bytes)}
    camera = GateCamera(programs)
    with pytest.raises(UnsupportedFirmware) as error:
        camera.identify_programs(programs[AP], programs[CP])
    assert str(error.value) == refusal(programs) and camera.firmware_build is None


def test_a_later_refusal_clears_an_earlier_identification(tmp_path):
    camera = identified(GateCamera)
    with pytest.raises(UnsupportedFirmware):
        camera.identify_programs(UNKNOWN[AP], UNKNOWN[CP])
    assert camera.firmware_build is None
    with pytest.raises(UnsupportedFirmware):
        camera.require_build()
    with pytest.raises(UnsupportedFirmware):
        camera.property_write(0x02cf0001, b'\0', {0x02cf0001})
    assert camera.link.writes() == []


def test_require_build_returns_the_identified_build():
    assert identified(GateCamera).require_build() is PUBLIC


# Each job type that writes identifies the programs it has just read, before its first write.

def run_audition(camera, folder):
    native = folder / 'native'
    native.mkdir()
    (native / 'job.private.json').write_text(json.dumps(
        dict(phase='written', complete_readback_and_settings_verified=True, identity=BODY)))
    with patch.object(trial, 'factory', lambda expected=None: camera):
        return buffer_trial.run(folder / 'audition', native)


def run_portrait(camera, folder):
    return portraitjob.PortraitJob(folder / 'frames', factory=lambda: camera).run_frames(
        True, version='2.01', power_confirmed=True)


def run_vertical(camera, folder):
    return vertical.execute('enable', folder / 'vertical', camera_factory=lambda expected=None: camera)


def run_names_reload(camera, folder):
    return namespause.verify_files(camera, folder, {'program_builds': []})


JOBS = {
    'Rollback.capture': (CheckpointGateCamera, lambda camera, folder: checkpointjob.Rollback(folder).capture(camera)),
    'DirectJob.capture': (CheckpointGateCamera, lambda camera, folder: direct.DirectJob(folder).capture(camera)),
    'Camera.pin_programs (LUT jobs, vertical)': (
        GateCamera, lambda camera, folder: camera.pin_programs(camera.read(AP), camera.read(CP))),
    'trial.capture (shutter sound)': (SoundGateCamera, lambda camera, folder: trial.capture(camera)),
    'buffer_trial.run (sound audition)': (SoundGateCamera, run_audition),
    'PortraitJob.run_frames': (GateCamera, run_portrait),
    'vertical.execute': (GateCamera, run_vertical),
    'namespause.verify_files': (GateCamera, run_names_reload),
}


@pytest.mark.parametrize('job', JOBS)
def test_each_job_identifies_the_programs_it_reads_before_writing(job, tmp_path):
    cls, run = JOBS[job]
    camera = unidentified(cls)
    with pytest.raises(UnsupportedFirmware) as error:
        run(camera, tmp_path)
    assert str(error.value) == refusal(UNKNOWN)
    assert camera.link.writes() == [] and camera.firmware_build is None


@pytest.mark.parametrize('job', ['Rollback.capture', 'Camera.pin_programs (LUT jobs, vertical)',
                                 'trial.capture (shutter sound)', 'namespause.verify_files'])
def test_identification_uses_exactly_the_programs_read(job, tmp_path):
    cls, run = JOBS[job]
    files = {AP: b'camera appFw.so', CP: b'camera cpapp-b.bin',
             **{'/usr/share/app/' + name: b'names' for name in nameworker.filenames()}}
    camera = cls(files)
    seen = []

    def identify(ap, cp):
        seen.append((ap, cp))
        return PUBLIC
    with patch.object(buildprofile, 'identify', identify), \
         patch('looktool.device_layout.identify', return_value={}), \
         patch('looktool.device_layout.structural', return_value={}):
        try:
            run(camera, tmp_path)
        except (KeyError, ValueError):  # later checks on these stand-in files
            pass
    assert seen == [(files[AP], files[CP])] and camera.firmware_build is PUBLIC


def test_direct_fl23_on_an_unknown_build_writes_nothing(tmp_path):
    from test_checkpoint import Camera, fake_compile, values
    from test_direct import SimDirect
    camera = Camera(values())
    camera.carries = None  # its programs are of no supported build
    before = copy.deepcopy((camera.files, camera.ram, camera.saved))
    job = SimDirect(tmp_path / 'fl23', factory=camera)
    with patch.object(Camera, '__call__', lambda obj, expected=None: obj), \
         patch.object(checkpointworker, 'compile_worker', side_effect=fake_compile), \
         pytest.raises(UnsupportedFirmware) as error:
        job.run_direct('fl23_enable', version='2.01', power_confirmed=True)
    programs = {path: camera.files[path] for path in (AP, CP)}
    assert str(error.value) == refusal(programs)
    assert (camera.files, camera.ram, camera.saved) == before
    assert camera.saves == [] and camera.native_calls == []
    assert job.state['phase'] == 'NEEDS_REVIEW' and job.state['error'] == refusal(programs)


# Read-only actions stay available on any build.

def test_connect_needs_no_identification(tmp_path):
    camera = unidentified(GateCamera)
    with patch.object(devicesession, 'Camera', lambda *args, **kwargs: camera):
        result = worker.run('connect', {}, tmp_path)
    assert result['model'] == 'ILCE-7CM2' and result['firmware_programs_written'] is False
    assert camera.firmware_build is None and camera.link.writes() == []


def test_usb_stability_needs_no_identification(tmp_path):
    from desktopapp import usbcheck
    programs = {AP: bytes(usbcheck.MIN_BYTES), CP: b'\1' * usbcheck.MIN_BYTES}
    camera = GateCamera(programs)
    report = usbcheck.run(tmp_path, factory=lambda: camera, clock=lambda: 0.0, min_seconds=0, min_rounds=2)
    assert report['phase'] == 'PASSED' and len(report['rounds']) == 2
    assert camera.firmware_build is None and camera.link.writes() == []


def launches(*results):
    """A stand-in worker that leaves its report files, as a read-only launch does."""
    def launch(files):
        for name, raw in results:
            files['/tmp/jiritsu/' + name] = raw
    return launch


VERTICAL_PROBE = vertical.struct.pack('<8sIIqQII24s', b'A7VUI001', 1, 16, 0, vertical.VALUE_RVA, 1, 0, bytes(24))
READ_ONLY = {
    "Rollback.native-runtime-0": (
        CheckpointGateCamera, launches(('a7c2.runtime.result', b'runtime'), ('a7c2.probe.result', b'probe')),
        lambda camera, folder: rollback('runtime', 0)[1](camera, folder)),
    'vertical.Workers.probe': (
        GateCamera, launches(('a7c2.runtime.result', VERTICAL_PROBE), ('a7c2.probe.result', b'probe')),
        lambda camera, folder: vertical.Workers(camera, journal()).probe()),
    'trial.run_native-probe-0': (
        SoundGateCamera, launches(('shutter.probe.result', b'sound'), ('a7c2.probe.result', b'probe')),
        lambda camera, folder: trial.run_native(camera, folder, {'journal': []}, worker_file(folder), 'probe')),
}


@pytest.mark.parametrize('launch', READ_ONLY)
def test_read_only_launches_need_no_identification(launch, tmp_path):
    cls, worker_run, run = READ_ONLY[launch]
    camera = cls(dict(UNKNOWN), worker_run)
    with patch.object(candidate, 'parse_probe', return_value=dict(image_mode='0')):
        run(camera, tmp_path)
    assert camera.firmware_build is None
    # Only staging in camera RAM, all of it removed again: no persistent write.
    assert {call[0] for call in camera.link.writes()} <= {'jiritsu16', 'jiritsu18'}
    assert all(path.startswith('/tmp/jiritsu/') for _, path in camera.link.writes())
    assert not [path for path in camera.link.files if path.startswith('/tmp/jiritsu/')]


# The refusal reads as plain text in the English interface.

def finish_failed_job(window, folder, error):
    job = folder / 'runs' / 'failed-job'
    job.mkdir(parents=True)
    write_json(job / 'status.private.json', dict(phase='FAILED', action='direct_fl23_enable', error=error))
    window.current_job, window.process = job, Mock()
    with patch.object(W.QMessageBox, 'information'), patch.object(W.QMessageBox, 'warning'):
        window.finished(2, None)
    return window.status.text()


UNSUPPORTED_ERROR = buildprofile.UNSUPPORTED % ('2ea02f7ecbc5bb91', 'f5a477588698ef96')


@pytest.mark.parametrize('refused,english', [
    ('unsupported', "This camera's firmware build isn't supported. Nothing was written. "
                    "(appFw.so 2ea02f7ecbc5bb91…, cpapp-b.bin f5a477588698ef96…)"),
    ('unidentified', "This camera's firmware build hasn't been identified, so nothing was written")])
def test_firmware_refusals_are_shown_in_english(window, tmp_path, refused, english):
    error = UNSUPPORTED_ERROR if refused == 'unsupported' else devicesession.UNIDENTIFIED
    text = finish_failed_job(window(language='en'), tmp_path, error)
    assert text == 'Operation stopped: ' + english + '. Please export diagnostics.'
    assert not HAN.search(text)


def test_firmware_refusal_stays_verbatim_in_chinese(window, tmp_path):
    text = finish_failed_job(window(), tmp_path, UNSUPPORTED_ERROR)
    assert text == '操作停止：' + UNSUPPORTED_ERROR + '。请导出诊断包。'


def test_refusal_digests_are_read_only_from_the_refusal_message():
    assert buildprofile.unsupported_digests(UNSUPPORTED_ERROR) == ('2ea02f7ecbc5bb91', 'f5a477588698ef96')
    for other in ('读取 appFw.so 失败：0x3528804', UNSUPPORTED_ERROR + ' extra', '此相机' + UNSUPPORTED_ERROR,
                  buildprofile.UNSUPPORTED % ('XYZ', 'f5a477588698ef96')):
        assert buildprofile.unsupported_digests(other) is None


# R7: the legacy FL2/FL3 actions wrote through transport.Session directly; the desktop can no
# longer dispatch them, and nothing in the desktop app loads the standalone writers.

@pytest.mark.parametrize('action', ['fl23_prepare', 'fl23_install', 'fl23_verify'])
def test_legacy_fl23_actions_cannot_be_dispatched(action, tmp_path):
    assert action not in jobs.CAMERA_ACTIONS | jobs.POWER_ACTIONS | jobs.DIRECT_ACTIONS
    arguments = dict(workspace=str(tmp_path / 'fl23'), backup=str(tmp_path / 'backup'), firmware='2.01',
                     power_confirmed=True)
    with pytest.raises(ValueError, match='Unknown desktop action'):
        worker.run(action, arguments, tmp_path)
    assert 'desktop_fl23' not in sys.modules


def sources(*folders, exclude=()):
    for folder in folders:
        for path in sorted((ROOT / folder).rglob('*.py')):
            relative = path.relative_to(ROOT).as_posix()
            if '/tests/' not in relative and '/vendor/' not in relative and relative not in exclude:
                yield relative, ast.parse(path.read_text(encoding='utf-8'))


# The two standalone tools outside the desktop app (src/fl23 via FL23.cmd and launcher.py, and the
# camera_runtime CLI behind its own gui.py) drive transport.Session themselves.
STANDALONE = ('src/camera_runtime/app.py', 'src/fl23/workflow.py')
DESKTOP = ('src/desktopapp', 'src/looks/looktool', 'src/shutter_sound', 'src/vertical')


def test_desktop_code_never_loads_the_standalone_writers():
    found = []
    for relative, tree in sources(*DESKTOP):
        for node in ast.walk(tree):
            if isinstance(node, ast.Import) and any(alias.name in ('app', 'workflow') for alias in node.names):
                found.append((relative, node.lineno))
            if isinstance(node, ast.ImportFrom) and node.module in ('app', 'workflow'):
                found.append((relative, node.lineno))
            if isinstance(node, ast.Constant) and isinstance(node.value, str) and node.value.endswith(
                    ('camera_runtime/app.py', 'fl23/workflow.py')):
                found.append((relative, node.lineno))
    assert found == []


# Raw service commands: only the transports and the session that gates them may issue these.
RAW = {'jiritsu', 'ap_write', 'writeBackup', 'saveBackup', '_sendAdjustControlPacket', 'sendSenserPacket',
       # SonySenserCamera's other persistent writers (vendor/pmca/usb/sony.py), reachable through link.call.
       'writeFile', 'deleteFile', 'writeMemory', 'setBackupPresetData', 'setBackupId1', 'setTerminalEnable',
       '_sendFileControlPacket', '_sendMemoryDumpPacket', '_sendProductInfoPacket',
       # Writing libJit.so is the launch; only devicesession.invoke calls this.
       '_launch'}
# Writes a transport session offers; outside the session they are reachable only through a link.
LINK_WRITES = {'cp_write', 'temp', 'write'}
# All that code outside the session may load from a camera's link: reads and bookkeeping. Anything
# else (link.call, link.camera, an alias of the link itself) could reach a raw writer.
LINK_READS = {'read', 'cp_read', 'identity', 'healthy', '__enter__'}
SESSION = ('src/looks/looktool/devicesession.py', 'src/camera_runtime/transport.py', 'src/fl23/transport.py')
# The transports' own temp-file tables. They name libJit.so for transport.Session.temp, which only the
# standalone writers call.
TRANSPORT_TABLES = ('src/camera_runtime/core.py', 'src/fl23/core.py')


def through_link(node):
    receiver = node.value
    return ((isinstance(receiver, ast.Attribute) and receiver.attr == 'link')
            or (isinstance(receiver, ast.Name) and receiver.id in ('link', 'session')))


def offences(tree):
    """Every way the code in `tree` could write to the camera around the session's gate."""
    parents = {child: node for node in ast.walk(tree) for child in ast.iter_child_nodes(node)}
    found = []
    for node in ast.walk(tree):
        parent = parents.get(node)
        used = parent if isinstance(parent, ast.Attribute) and parent.value is node else None
        if isinstance(node, ast.Attribute) and node.attr in RAW:
            found.append((node.lineno, node.attr))
        elif isinstance(node, ast.Attribute) and node.attr in LINK_WRITES and through_link(node):
            found.append((node.lineno, node.attr))
        elif isinstance(node, ast.Attribute) and node.attr == 'link' and isinstance(node.ctx, ast.Load):
            # <x>.link: only a read or a bookkeeping store may follow it, never an alias of the link.
            if used is None or (isinstance(used.ctx, ast.Load) and used.attr not in LINK_READS):
                found.append((node.lineno, 'link.' + (used.attr if used else '')))
        elif (isinstance(node, ast.Name) and node.id == 'link' and used is not None
              and isinstance(used.ctx, ast.Load) and used.attr in ('call', 'camera')):
            found.append((node.lineno, 'link.' + used.attr))
        elif (isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == 'getattr'
              and len(node.args) > 1 and isinstance(node.args[1], ast.Constant) and node.args[1].value == 'link'):
            found.append((node.lineno, "getattr(…, 'link')"))
        elif isinstance(node, ast.Constant) and isinstance(node.value, str) and (
                node.value == devicesession.LAUNCHER or node.value.endswith('/' + devicesession.LAUNCHER)):
            found.append((node.lineno, node.value))
    return found


def test_no_module_writes_around_the_session():
    found = [(relative, *offence) for relative, tree in sources('src', exclude=SESSION + STANDALONE + TRANSPORT_TABLES)
             for offence in offences(tree)]
    assert found == []


def test_only_invoke_launches_a_worker():
    tree = ast.parse((ROOT / 'src/looks/looktool/devicesession.py').read_text(encoding='utf-8'))
    callers = {function.name for function in ast.walk(tree) if isinstance(function, ast.FunctionDef)
               for node in ast.walk(function)
               if isinstance(node, ast.Attribute) and node.attr == '_launch' and isinstance(node.ctx, ast.Load)}
    assert callers == {'invoke'}


@pytest.mark.parametrize('code,offence', [
    ('camera.link.cp_write(key, value)', 'link.cp_write'),
    ('camera.link.call(camera.link.camera.saveBackup, 0x02cf)', 'saveBackup'),
    ('self.link.jiritsu(16, data)', 'jiritsu'),
    ('session.temp(name, blob)', 'temp'),
    ('camera.link.call(camera.link.camera.setBackupPresetData, 1, data)', 'setBackupPresetData'),
    ('camera.link.call(reader, key)', 'link.call'),
    ('method = camera.link.camera.readBackup', 'link.camera'),
    ('link.call(link.camera.readBackup, key)', 'link.call'),
    ('s = camera.link\ns.cp_write(key, value)', 'link.'),
    ('send(camera.link)', 'link.'),
    ("s = getattr(camera, 'link')", "getattr(…, 'link')"),
    ("camera.temp_write('libJit.so', blob)", 'libJit.so'),
    ("camera.link.select('/tmp/jiritsu/libJit.so')", '/tmp/jiritsu/libJit.so'),
    ('camera._launch(blob)', '_launch'),
    ('camera.link.writeFile(path, data)', 'writeFile'),
])
def test_the_session_scan_sees_each_way_around_the_session(code, offence):
    assert offence in [label for _, label in offences(ast.parse(code))]


def test_the_session_scan_allows_reads_and_bookkeeping():
    code = ('camera.link.read(path)\nraw = camera.link.cp_read(key)\nok = camera.link.healthy\n'
            'self.identity = self.link.identity\nself.link.__enter__()\ncamera.link.mutating = True\n'
            'self.link = transport.Session(expected)\nlink.camera = transport.SonySenserCamera(link.channel)\n'
            'camera.temp_read(devicesession.LAUNCHER, True)\ncamera.property_write(key, value, keys)\n')
    assert offences(ast.parse(code)) == []


# The launcher: libJit.so is never staged, and a launch before model confirmation runs only runtime.so.

@pytest.mark.parametrize('cls', [GateCamera, CheckpointGateCamera, SoundGateCamera])
def test_staging_refuses_the_launcher_even_on_an_identified_build(cls):
    camera = identified(cls)
    with pytest.raises(ValueError, match=devicesession.NOT_STAGING):
        camera.temp_write(devicesession.LAUNCHER, b'\x7fELF test worker')
    with pytest.raises(ValueError, match=devicesession.NOT_STAGING):
        camera._jiritsu_write(devicesession.LAUNCHER, b'\x7fELF test worker')
    # The refusal names the launcher whatever else is wrong with the session.
    camera.programs_pinned, camera.identity_pending = False, True
    with pytest.raises(ValueError, match=devicesession.NOT_STAGING):
        camera.temp_write(devicesession.LAUNCHER, b'\x7fELF test worker')
    assert camera.link.calls == []


def test_launch_before_model_confirmation_runs_only_the_pinned_runtime_probe():
    runtime = (ROOT / 'src/fl23/assets/runtime.so').read_bytes()
    camera = identified(GateCamera)
    camera.identity_pending = True
    camera.core.assets = lambda: {'files': {'runtime.so': hashlib.sha256(runtime).hexdigest()}}
    with pytest.raises(ValueError, match='pinned read-only'):
        camera._launch(b'\x7fELF other worker')
    assert camera.link.writes() == []
    camera._launch(runtime)
    assert camera.link.writes() == [('jiritsu16', '/tmp/jiritsu/' + devicesession.LAUNCHER)]
