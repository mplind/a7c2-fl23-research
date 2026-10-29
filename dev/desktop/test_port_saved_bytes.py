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
from buildfixtures import assert_nothing_written, unchanged
import test_checkpoint as simulated
from test_checkpoint import Camera, KEYS, SimRollback, fake_compile, values
from guihelpers import HAN_OR_PUNCTUATION
from simbuild import saved_as
from soundbench import STOCK, SoundBench

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'src/shutter_sound'))
import boot_trial  # noqa: E402

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

SAVED_PROGRAMS = {'appFw.so': STOCK['/usr/lib/appFw.so'], 'cpapp-b.bin': STOCK['/cp/cpapp-b.bin']}


@pytest.fixture
def bench():
    """boot_trial's Save and Restore with every native step simulated (soundbench, shared with
    dev/shutter_sound/tests/test_boot_trial.py)."""
    with SoundBench() as sound:
        yield sound


def job_state(job):
    return json.loads((job / 'job.private.json').read_text(encoding='utf-8'))


def forget_build(job):
    """Make `job` one saved before builds were recorded."""
    state = job_state(job)
    del state['firmware_build']
    (job / 'job.private.json').write_text(json.dumps(state), encoding='utf-8')


@pytest.mark.parametrize('build', BUILDS, ids=[build.key for build in BUILDS])
def test_sound_jobs_record_their_build(tmp_path, bench, build):
    job = bench.install(tmp_path, build)
    assert job_state(job)['firmware_build'] == build.key
    with zipfile.ZipFile(job / 'before.private.zip') as saved:
        assert {name: saved.read(name) for name in PROGRAMS} == SAVED_PROGRAMS


def test_a_public_sound_job_is_refused_on_a_body_camera_before_any_write(tmp_path, bench):
    job = bench.install(tmp_path, PUBLIC)
    bench.events.clear()
    before = dict(bench.files)
    with pytest.raises(buildprofile.OtherBuild) as error:
        boot_trial.restore(job, camera_factory=bench.connect(BODY))
    assert str(error.value) == buildprofile.SAVED_OTHER_BUILD % (PUBLIC.key, BODY.key)
    assert bench.events == ['connect'] and bench.files == before


@pytest.mark.parametrize('build', BUILDS, ids=[build.key for build in BUILDS])
def test_a_same_build_sound_job_restores(tmp_path, bench, build):
    job = bench.install(tmp_path, build)
    assert boot_trial.restore(job, camera_factory=bench.connect(build))['phase'] == 'restored_cold_test_pending'
    assert bench.files == STOCK


def test_an_old_sound_job_is_identified_from_its_saved_programs(tmp_path, bench):
    job = bench.install(tmp_path / 'body', BODY)
    forget_build(job)
    with saved_as(BODY, SAVED_PROGRAMS) as identify:
        assert boot_trial.restore(job, camera_factory=bench.connect(BODY))['phase'] == 'restored_cold_test_pending'
    identify.assert_called_once_with(*SAVED_PROGRAMS.values())
    assert bench.files == STOCK
    job = bench.install(tmp_path / 'public', BODY)
    forget_build(job)
    bench.events.clear()
    before = dict(bench.files)
    with saved_as(BODY, SAVED_PROGRAMS), pytest.raises(buildprofile.OtherBuild) as error:
        boot_trial.restore(job, camera_factory=bench.connect(PUBLIC))
    assert str(error.value) == buildprofile.SAVED_OTHER_BUILD % (BODY.key, PUBLIC.key)
    assert bench.events == ['connect'] and bench.files == before


def legacy_job(tmp_path, bench):
    """A Save job from before jobs recorded their build, whose saved copy holds no programs (a
    sound-resource replacement): no build can be named for it."""
    job = bench.install(tmp_path, BODY)
    forget_build(job)
    with zipfile.ZipFile(job / 'before.private.zip', 'w') as saved:
        saved.writestr('custom.txt', b'previous CSV')
    bench.events.clear()
    return job


def test_an_old_sound_job_of_no_identifiable_build_is_refused_unopened(tmp_path, bench):
    job = bench.install(tmp_path, BODY)
    forget_build(job)
    bench.events.clear()
    with pytest.raises(buildprofile.OtherBuild, match=buildprofile.SAVED_UNIDENTIFIED):
        boot_trial.restore(job, camera_factory=bench.connect(BODY))    # stand-ins identify as no build
    assert bench.events == []
    job = legacy_job(tmp_path / 'resources-only', bench)
    with saved_as(BODY, SAVED_PROGRAMS), pytest.raises(buildprofile.OtherBuild, match=buildprofile.SAVED_UNIDENTIFIED):
        boot_trial.restore(job, camera_factory=bench.connect(BODY))
    assert bench.events == []


def test_an_old_sound_job_of_no_identifiable_build_is_retired_with_a_next_step(tmp_path, bench, capsys):
    # B1 (RESTORE-SOUND-LEGACY): such a job can never restore, so restore-sound must not pick it again
    # and again; it is retired, and the user is told what to do instead.
    import sound_cli
    job = legacy_job(tmp_path, bench)
    phase = job_state(job)['phase']
    assert sound_cli.restorable_install(tmp_path, {'boot_job': str(job)}) == job
    with pytest.raises(buildprofile.OtherBuild, match=buildprofile.SAVED_UNIDENTIFIED):
        boot_trial.restore(job, camera_factory=bench.connect(BODY))
    state = job_state(job)
    assert (state['phase'], state['retired_from']) == ('retired_build_unknown', phase)
    assert sound_cli.restorable_install(tmp_path, {'boot_job': str(job)}) is None
    assert boot_trial.RETIRED_UNKNOWN_BUILD in capsys.readouterr().out
    assert bench.events == []
    with pytest.raises(ValueError, match='Inspect the original job'):  # never tried again
        boot_trial.restore(job, camera_factory=bench.connect(BODY))


def test_the_retired_job_next_step_reads_in_english():
    from desktopapp.engine_text import translate_text
    shown = translate_text(boot_trial.RETIRED_UNKNOWN_BUILD)
    assert not HAN_OR_PUNCTUATION.search(shown) and 'Restore' in shown


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

