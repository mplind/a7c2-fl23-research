"""Restores from saved bytes refuse a camera of another build (R13/R27).

A backup (an initial checkpoint, restored by Rollback from the worker's restore and restore_auto
actions and recovery.py) and a shutter-sound Save job (boot_trial, restored from its saved windows)
both hold one build's program bytes. They record that build when they save, and a restore refuses,
before any camera write, a camera whose identified build differs. Bytes saved before builds were
recorded are identified from the programs saved with them; when those don't identify, or weren't
saved, the restore is refused.

Cameras are simulated with stand-in programs that play a named build (simbuild.CarriesBuild); the
real-firmware tests read A7C2_BUILD_FIXTURES through conftest.py and skip when it is unset.
"""
from contextlib import contextmanager
import copy
import json
from pathlib import Path
import sys
import zipfile
from unittest.mock import patch

import pytest

from desktopapp import recovery, worker
from looktool import buildprofile, checkpoint, checkpointworker
from looktool.buildprofile import BUILDS
import test_checkpoint as simulated
from test_checkpoint import Camera, KEYS, SimRollback, fake_compile, values
from test_language import finish_failed_job
from guihelpers import HAN_OR_PUNCTUATION, stopped_banner
from simbuild import CarriesBuild, saved_as

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'src/shutter_sound'))
import boot_trial  # noqa: E402
import trial  # noqa: E402

PUBLIC, BODY = BUILDS
PROGRAMS = ('appFw.so', 'cpapp-b.bin')


# Backups ---------------------------------------------------------------------------------------

@pytest.fixture
def offline(monkeypatch, tmp_path):
    monkeypatch.setattr(checkpointworker, 'compile_worker', fake_compile)
    monkeypatch.setattr(checkpoint, 'recipe_keys', lambda ap: KEYS)
    monkeypatch.setenv('A7C2_DESKTOP_DATA', str(tmp_path / 'desktop-data'))


def backup(folder, **build):
    """An initial checkpoint of the simulated body; build=… records the build it was saved from, and
    without it the checkpoint is one saved before builds were recorded."""
    path = folder / 'backup2' / 'checkpoint.private.zip'
    checkpoint.write(path, values(), simulated.BODY, provenance={'type': 'test-initial'}, **build)
    return path


def updated_camera(build):
    """The simulated body after later look edits, its stand-in programs playing `build`."""
    camera = Camera(values())
    for path in checkpoint.PROGRAM_PATHS.values():
        data = bytearray(camera.files[path])
        data[0:100] = bytes([3]) * 100
        camera.files[path] = bytes(data)
    for key in KEYS:
        camera._set(0, key, b'\x09')
    camera.saved = copy.deepcopy(camera.ram)
    camera.carries = build
    return camera


def unchanged(camera):
    return copy.deepcopy((camera.files, camera.ram, camera.saved))


def assert_nothing_written(camera, before):
    assert camera.native_calls == [] and camera.saves == []
    assert (camera.files, camera.ram, camera.saved) == before


def restored(camera):
    return {name: camera.files[path] for name, path in checkpoint.PROGRAM_PATHS.items()}


def rollback(archive, camera, folder):
    return SimRollback(folder / 'rollback', factory=camera).run(archive, 100, '2.01')


def worker_restore(archive, camera, folder):
    """The desktop restore action (worker.run 'restore'), on simulated camera `camera`."""
    job = folder / 'job'
    job.mkdir()
    with patch('looktool.checkpointjob.Rollback', side_effect=lambda root: SimRollback(root, factory=camera)):
        return worker.run('restore', dict(workspace=str(folder / 'rollback'), backup=str(archive), battery=100,
                                          firmware='2.01', power_confirmed=True), job)


def automatic_restore(archive, camera, folder):
    """The desktop restore_auto action (recovery.restore_auto) over the registered backup."""
    with patch('desktopapp.recovery.data_root', return_value=folder / 'data'):
        (folder / 'data').mkdir()
        recovery.register(archive)

        @contextmanager
        def connect():
            yield camera
        return recovery.restore_auto(dict(firmware='2.01', battery=100, power_confirmed=True,
                                          workspace=str(folder / 'rollback')), folder,
                                     factory=connect, rollback_type=SimRollback)


ENTRIES = {'rollback': rollback, 'restore': worker_restore, 'restore_auto': automatic_restore}


def test_backups_record_the_build_they_were_saved_from(tmp_path, offline):
    assert checkpoint.read(backup(tmp_path / 'new', build=BODY))[0]['firmware_build'] == BODY.key
    assert 'firmware_build' not in checkpoint.read(backup(tmp_path / 'old'))[0]
    camera = updated_camera(BODY)
    rollback(backup(tmp_path / 'restore', build=BODY), camera, tmp_path / 'restore')
    # The rollback's own copy of the camera, taken before it writes, records the camera's build.
    manifest, _ = checkpoint.read(tmp_path / 'restore' / 'rollback' / 'before.private.zip')
    assert manifest['firmware_build'] == BODY.key


@pytest.mark.parametrize('entry', sorted(ENTRIES))
def test_a_public_backup_is_refused_on_a_body_camera_before_any_write(tmp_path, offline, entry):
    archive = backup(tmp_path, build=PUBLIC)
    camera = updated_camera(BODY)
    before = unchanged(camera)
    with pytest.raises(buildprofile.OtherBuild) as error:
        ENTRIES[entry](archive, camera, tmp_path)
    assert str(error.value) == buildprofile.SAVED_OTHER_BUILD % (PUBLIC.key, BODY.key)
    assert_nothing_written(camera, before)
    state = json.loads((tmp_path / 'rollback' / 'rollback.private.json').read_text(encoding='utf-8'))
    assert state['phase'] == 'NEEDS_REVIEW' and state['firmware_build'] == PUBLIC.key


def test_verifying_a_refused_restore_never_opens_the_camera(tmp_path, offline):
    archive = backup(tmp_path, build=PUBLIC)
    camera = updated_camera(BODY)
    with pytest.raises(buildprofile.OtherBuild):
        worker_restore(archive, camera, tmp_path)
    before = unchanged(camera)
    with patch('looktool.checkpointjob.Rollback', side_effect=lambda root: SimRollback(root, factory=camera)), \
         pytest.raises(ValueError, match='Rollback did not finish'):
        worker.run('restore_verify', dict(workspace=str(tmp_path / 'rollback')), tmp_path)
    assert_nothing_written(camera, before)


@pytest.mark.parametrize('build', BUILDS, ids=[build.key for build in BUILDS])
@pytest.mark.parametrize('entry', sorted(ENTRIES))
def test_a_same_build_backup_restores(tmp_path, offline, build, entry):
    camera = updated_camera(build)
    result = ENTRIES[entry](backup(tmp_path, build=build), camera, tmp_path)
    assert result['phase'] == 'RESTORED_AWAITING_RELOAD'
    assert restored(camera) == {name: values()[name] for name in PROGRAMS}


def test_an_old_backup_is_identified_from_its_programs(tmp_path, offline):
    archive = backup(tmp_path)
    saved = {name: values()[name] for name in PROGRAMS}
    camera = updated_camera(BODY)
    with saved_as(BODY, saved) as identify:
        assert rollback(archive, camera, tmp_path / 'body')['phase'] == 'RESTORED_AWAITING_RELOAD'
    identify.assert_called_once_with(saved['appFw.so'], saved['cpapp-b.bin'])
    assert restored(camera) == saved
    camera = updated_camera(PUBLIC)
    before = unchanged(camera)
    with saved_as(BODY, saved), pytest.raises(buildprofile.OtherBuild) as error:
        rollback(archive, camera, tmp_path / 'public')
    assert str(error.value) == buildprofile.SAVED_OTHER_BUILD % (BODY.key, PUBLIC.key)
    assert_nothing_written(camera, before)


def test_an_old_backup_whose_programs_identify_as_no_build_is_refused_unopened(tmp_path, offline):
    archive = backup(tmp_path)
    opened = []
    job = SimRollback(tmp_path / 'rollback', factory=lambda expected=None: opened.append(expected))
    with pytest.raises(buildprofile.OtherBuild) as error:
        job.run(archive, 100, '2.01')    # the stand-in programs are no supported build
    assert str(error.value) == buildprofile.SAVED_UNIDENTIFIED
    assert opened == [] and not job.root.exists()


def legacy_folder(folder):
    """The original FL23 tool's own raw backup (checkpoint.read_legacy), with no build recorded."""
    folder.mkdir()
    for name in PROGRAMS:
        (folder / (name + '.bin')).write_bytes(values()[name])
    (folder / 'backup.private.bin').write_bytes(values()['settings-ram.bin'])
    return folder


def test_an_old_fl23_backup_folder_is_identified_from_its_programs(tmp_path, offline):
    from types import SimpleNamespace
    folder = legacy_folder(tmp_path / 'original-backup2')
    saved = {name: values()[name] for name in PROGRAMS}
    legacy = patch('looktool.devicesession.modules', return_value=(None, SimpleNamespace(backup_records=simulated.records)))
    camera = updated_camera(PUBLIC)
    with legacy, saved_as(PUBLIC, saved):
        assert rollback(folder, camera, tmp_path / 'public')['phase'] == 'RESTORED_AWAITING_RELOAD'
    manifest, _ = checkpoint.read(tmp_path / 'public' / 'rollback' / 'target.private.zip')
    assert manifest['firmware_build'] == PUBLIC.key
    camera = updated_camera(BODY)
    before = unchanged(camera)
    with legacy, saved_as(PUBLIC, saved), pytest.raises(buildprofile.OtherBuild):
        rollback(folder, camera, tmp_path / 'body')
    assert_nothing_written(camera, before)


def test_saved_programs_identify_as_their_own_build(build_fixtures):
    for build, fixture in ((PUBLIC, build_fixtures.public), (BODY, build_fixtures.body)):
        assert buildprofile.saved_build(None, {'appFw.so': fixture.ap, 'cpapp-b.bin': fixture.cp}) is build
    with pytest.raises(buildprofile.OtherBuild) as error:
        buildprofile.saved_build(None, {'appFw.so': build_fixtures.hybrid.ap, 'cpapp-b.bin': build_fixtures.hybrid.cp})
    assert str(error.value) == buildprofile.SAVED_UNIDENTIFIED


def test_a_recorded_build_is_taken_as_recorded():
    with patch.object(buildprofile, 'identify', side_effect=AssertionError('identified')):
        for build in BUILDS:
            assert buildprofile.saved_build(build.key, None) is build
        for recorded, programs in (('public-2.02', None), (None, None), (None, {'appFw.so': b'only one'})):
            with pytest.raises(buildprofile.OtherBuild, match=buildprofile.SAVED_UNIDENTIFIED):
                buildprofile.saved_build(recorded, programs)


# Shutter-sound Save jobs -----------------------------------------------------------------------

IDENTITY = {'model': 'ILCE-7CM2', 'serial_sha256': 'synthetic'}
STOCK = {'/usr/lib/appFw.so': b'original-unrelated', '/cp/cpapp-b.bin': b'unchanged CP'}
SAVED_PROGRAMS = {'appFw.so': STOCK['/usr/lib/appFw.so'], 'cpapp-b.bin': STOCK['/cp/cpapp-b.bin']}


class SoundCamera(CarriesBuild):
    core = None

    def __init__(self, files, build):
        self.files, self.carries = files, build

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def read(self, path, missing=False):
        return self.files.get(path) if missing else self.files[path]

    def snapshot(self, memory):
        return b'unchanged settings'

    def records(self, raw):
        return raw


@pytest.fixture
def bench(tmp_path):
    """boot_trial's install and restore with every native step simulated (as test_boot_trial.py does):
    yields (files, events, connect), where connect(build) opens a camera playing `build`."""
    files, events = dict(STOCK), []

    def connect(build):
        def factory(expected):
            assert expected == IDENTITY
            events.append('connect')
            return SoundCamera(files, build)
        return factory

    def prepare(ap, cp, value, output, zig, *, build):
        root = Path(output)
        root.mkdir()
        (root / 'audio').write_bytes(value)
        (root / 'csv').write_bytes(b'private CSV')
        return {'appFw.so': b'modified' + ap[8:], 'cpapp-b.bin': cp}, {
            'windows': [{'offset': 0, 'before_hex': b'original'.hex(), 'after_hex': b'modified'.hex()}],
            'program': {'path': 'forward', 'windows': 1, 'sizes': [len(ap), len(cp)]},
            'files': 'fileworker', 'probe': 'probe', 'wbi': 'wbi',
            'audio': str(root / 'audio'), 'csv': str(root / 'csv')}

    def invoke_files(camera, root, state, worker_path, mode):
        events.append(('files', mode))
        if mode == 1:
            for path, name in zip(boot_trial.PATHS, ('audio', 'csv')):
                files[path] = Path(state['components'][name]).read_bytes()
        elif mode == 2:
            for path in boot_trial.PATHS:
                del files[path]
        return {'native_success': True}

    def run_native(camera, root, state, blob, kind, mode=0, plan=None):
        events.append((kind, mode, str(blob)))
        if kind == 'program' and mode == 1:
            prefix = b'original' if str(blob) == 'reverse' else b'modified'
            files['/usr/lib/appFw.so'] = prefix + files['/usr/lib/appFw.so'][8:]
        return {}

    def probe(camera, root, state, components):
        events.append('probe')
        return {'image_mode': '0'}

    def reverse_worker(ap, cp, edits, output, zig):
        return {'path': 'reverse', 'windows': 1, 'sizes': [len(ap), len(cp)]}

    with patch.object(boot_trial, 'prepare', prepare), patch.object(boot_trial, 'invoke_files', invoke_files), \
         patch.object(boot_trial, 'probe', probe), patch.object(boot_trial, 'program_worker', reverse_worker), \
         patch.object(boot_trial, 'require_dependencies'), patch.object(trial, 'run_native', run_native), \
         patch('looktool.devicesettings.compare'):
        yield files, events, connect


def install(folder, connect, build):
    """A completed shutter-sound Save on a camera playing `build`; the job folder."""
    native, audio, job = folder / 'native', folder / 'audio', folder / 'job'
    folder.mkdir(parents=True, exist_ok=True)
    payload = bytes(64)
    for path, value in ((native, {'identity': IDENTITY}),
                        (audio, {'identity': IDENTITY, 'wire_format': 0, 'owner_audio_correct': True})):
        path.mkdir()
        (path / 'job.private.json').write_text(json.dumps(value))
    (audio / 'payload.private.bin').write_bytes(payload)
    boot_trial.install(job, folder / 'backup2', native, audio, payload, 100, camera_factory=connect(build))
    return job


def job_state(job):
    return json.loads((job / 'job.private.json').read_text(encoding='utf-8'))


def forget_build(job):
    """Make `job` one saved before builds were recorded."""
    state = job_state(job)
    del state['firmware_build']
    (job / 'job.private.json').write_text(json.dumps(state), encoding='utf-8')


@pytest.mark.parametrize('build', BUILDS, ids=[build.key for build in BUILDS])
def test_sound_jobs_record_their_build(tmp_path, bench, build):
    _, _, connect = bench
    job = install(tmp_path, connect, build)
    assert job_state(job)['firmware_build'] == build.key
    with zipfile.ZipFile(job / 'before.private.zip') as saved:
        assert {name: saved.read(name) for name in PROGRAMS} == SAVED_PROGRAMS


def test_a_public_sound_job_is_refused_on_a_body_camera_before_any_write(tmp_path, bench):
    files, events, connect = bench
    job = install(tmp_path, connect, PUBLIC)
    events.clear()
    before = dict(files)
    with pytest.raises(buildprofile.OtherBuild) as error:
        boot_trial.restore(job, camera_factory=connect(BODY))
    assert str(error.value) == buildprofile.SAVED_OTHER_BUILD % (PUBLIC.key, BODY.key)
    assert events == ['connect'] and files == before


@pytest.mark.parametrize('build', BUILDS, ids=[build.key for build in BUILDS])
def test_a_same_build_sound_job_restores(tmp_path, bench, build):
    files, events, connect = bench
    job = install(tmp_path, connect, build)
    assert boot_trial.restore(job, camera_factory=connect(build))['phase'] == 'restored_cold_test_pending'
    assert files == STOCK


def test_an_old_sound_job_is_identified_from_its_saved_programs(tmp_path, bench):
    files, events, connect = bench
    job = install(tmp_path / 'body', connect, BODY)
    forget_build(job)
    with saved_as(BODY, SAVED_PROGRAMS) as identify:
        assert boot_trial.restore(job, camera_factory=connect(BODY))['phase'] == 'restored_cold_test_pending'
    identify.assert_called_once_with(*SAVED_PROGRAMS.values())
    assert files == STOCK
    job = install(tmp_path / 'public', connect, BODY)
    forget_build(job)
    events.clear()
    before = dict(files)
    with saved_as(BODY, SAVED_PROGRAMS), pytest.raises(buildprofile.OtherBuild) as error:
        boot_trial.restore(job, camera_factory=connect(PUBLIC))
    assert str(error.value) == buildprofile.SAVED_OTHER_BUILD % (BODY.key, PUBLIC.key)
    assert events == ['connect'] and files == before


def test_an_old_sound_job_of_no_identifiable_build_is_refused_unopened(tmp_path, bench):
    files, events, connect = bench
    job = install(tmp_path, connect, BODY)
    forget_build(job)
    events.clear()
    phase = job_state(job)['phase']
    with pytest.raises(buildprofile.OtherBuild, match=buildprofile.SAVED_UNIDENTIFIED):
        boot_trial.restore(job, camera_factory=connect(BODY))    # stand-ins identify as no build
    # A job whose saved copy holds no programs (a sound-resource replacement) can't be identified either.
    with zipfile.ZipFile(job / 'before.private.zip', 'w') as saved:
        saved.writestr('custom.txt', b'previous CSV')
    with saved_as(BODY, SAVED_PROGRAMS), pytest.raises(buildprofile.OtherBuild, match=buildprofile.SAVED_UNIDENTIFIED):
        boot_trial.restore(job, camera_factory=connect(BODY))
    assert events == [] and job_state(job)['phase'] == phase


def test_an_old_sound_job_holding_real_programs_identifies_their_build(build_fixtures, tmp_path):
    for name, fixture, build in (('body', build_fixtures.body, BODY), ('public', build_fixtures.public, PUBLIC),
                                 ('hybrid', build_fixtures.hybrid, None)):
        root = tmp_path / name
        root.mkdir()
        with zipfile.ZipFile(root / 'before.private.zip', 'x', zipfile.ZIP_STORED) as saved:
            saved.writestr('appFw.so', fixture.ap)
            saved.writestr('cpapp-b.bin', fixture.cp)
            saved.writestr('settings-ram.bin', b'settings')
        if build is None:
            with pytest.raises(buildprofile.OtherBuild, match=buildprofile.SAVED_UNIDENTIFIED):
                boot_trial.saved_build(root, {'phase': 'installed_cold_test_pending'})
        else:
            assert boot_trial.saved_build(root, {'phase': 'installed_cold_test_pending'}) is build


# The refusals, in English ----------------------------------------------------------------------

@pytest.mark.parametrize('template, values, english', [
    ('SAVED_OTHER_BUILD', ('public-2.01', 'body-2.01-20250923'),
     'The saved bytes come from firmware build public-2.01, but the camera is body-2.01-20250923. Nothing was written.'),
    ('SAVED_UNIDENTIFIED', (), "The firmware build of the saved bytes can't be identified, so nothing was written."),
])
def test_saved_bytes_refusals_are_shown_in_english(window, tmp_path, template, values, english):
    error = getattr(buildprofile, template) % values if values else getattr(buildprofile, template)
    text = finish_failed_job(window(language='en'), tmp_path, error)
    assert text == stopped_banner(english)
    assert not HAN_OR_PUNCTUATION.search(text)


def test_the_refusals_stay_verbatim_in_chinese(window, tmp_path):
    # The refusal ends its sentence, so the banner adds no second full stop.
    error = buildprofile.SAVED_OTHER_BUILD % (PUBLIC.key, BODY.key)
    assert finish_failed_job(window(), tmp_path, error) == '操作停止：' + error + '请导出诊断包。'
