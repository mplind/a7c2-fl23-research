"""A job gets the camera's program bytes one way, Camera.read_programs, which identifies them once; the
planners take that build and never identify again (R61). No camera: the sessions are the production
classes over an in-memory link (test_firmware_gate), and the real-firmware cases read
A7C2_BUILD_FIXTURES.
"""
import ast
import json
from pathlib import Path
import sys
from unittest.mock import patch

import pytest

from desktopapp import allinone, worker
from looktool import buildprofile, bundle, checkpoint, devicesession, direct, verticalpersist
from looktool.buildprofile import BUILDS

from test_firmware_gate import AP, CP, UNKNOWN, GateCamera  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
PUBLIC, BODY = BUILDS


def counting(build=PUBLIC):
    """buildprofile.identify replaced by one that answers `build` and counts its calls."""
    return patch.object(buildprofile, 'identify', return_value=build)


# Camera.read_programs --------------------------------------------------------------------------

def test_read_programs_reads_both_programs_once_and_identifies_them():
    camera = GateCamera(dict(UNKNOWN))
    with counting() as identify:
        programs = camera.read_programs()
    assert programs == {'appFw.so': UNKNOWN[AP], 'cpapp-b.bin': UNKNOWN[CP]}
    identify.assert_called_once_with(UNKNOWN[AP], UNKNOWN[CP])
    assert camera.firmware_build is PUBLIC
    assert [call for call in camera.link.calls if call[0] == 'read'] == [('read', AP), ('read', CP)]


def test_read_programs_refuses_an_unsupported_camera():
    camera = GateCamera(dict(UNKNOWN))
    with pytest.raises(buildprofile.UnsupportedFirmware):
        camera.read_programs()
    assert camera.firmware_build is None


def test_pinning_the_programs_just_read_identifies_nothing_again():
    camera = GateCamera(dict(UNKNOWN))
    camera.programs_pinned = False
    with counting() as identify, patch('looktool.device_layout.identify', return_value={'kind': 'stock'}) as layout:
        programs = camera.read_programs()
        camera.pin_programs(programs['appFw.so'], programs['cpapp-b.bin'])
    identify.assert_called_once()
    layout.assert_called_once_with(UNKNOWN[AP], UNKNOWN[CP], build=PUBLIC)
    assert camera.programs_pinned


def test_pinning_other_programs_identifies_them():
    camera = GateCamera(dict(UNKNOWN))
    with counting() as identify, patch('looktool.device_layout.identify', return_value={'kind': 'stock'}):
        camera.read_programs()
        camera.pin_programs(b'other appFw.so', b'other cpapp-b.bin')
    assert identify.call_count == 2 and identify.call_args.args == (b'other appFw.so', b'other cpapp-b.bin')


# Every job reads its programs through read_programs: no other read of the two program paths.
JOB_SOURCES = ('src/desktopapp/worker.py', 'src/looks/looktool/checkpointjob.py', 'src/shutter_sound/trial.py',
               'src/shutter_sound/buffer_trial.py', 'src/looks/looktool/portraitjob.py',
               'src/desktopapp/actions/sound_state.py', 'src/looks/looktool/namespause.py',
               'src/vertical/verticaltool/device.py')


@pytest.mark.parametrize('relative', JOB_SOURCES)
def test_no_job_reads_and_identifies_the_programs_itself(relative):
    tree = ast.parse((ROOT / relative).read_text(encoding='utf-8'))
    calls = [node for node in ast.walk(tree) if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)]
    assert not [call.lineno for call in calls if call.func.attr == 'identify_programs']
    program_reads = [call.lineno for call in calls if call.func.attr == 'read' and call.args
                     and isinstance(call.args[0], ast.Constant) and call.args[0].value in (AP, CP)]
    assert program_reads == []
    assert any(call.func.attr == 'read_programs' for call in calls)


# The connection test, and the one-click recheck after a driver step --------------------------------

def test_connect_identifies_by_default_and_not_when_asked_not_to(tmp_path):
    for arguments, reads in (({}, [AP, CP]), ({'identify': False}, [])):
        camera = GateCamera(dict(UNKNOWN))
        with counting() as identify, patch.object(devicesession, 'Camera', lambda *a, **k: camera):
            result = worker.run('connect', arguments, tmp_path)
        assert [call[1] for call in camera.link.calls if call[0] == 'read'] == reads
        assert ('firmware_build' in result) is bool(reads) and identify.call_count == (1 if reads else 0)


def test_the_one_click_driver_recheck_only_opens_the_connection(tmp_path):
    calls = []

    def dispatch(action, arguments, step):
        calls.append((action, arguments))
        if action == 'usb_prepare':
            raise RuntimeError('Driver setup not completed')
        raise RuntimeError('stop after the recheck')
    arguments = dict(workspace=str(tmp_path / 'setup'), firmware='2.01', power_confirmed=True,
                     options=dict(fl23=True, sound=False, vertical=False, plugin=False, looks=[]))
    for _ in range(2):
        with pytest.raises(RuntimeError):
            allinone.run(arguments, dispatch=dispatch)
    assert calls[:2] == [('usb_prepare', {}), ('connect', {'identify': False})]
    state = json.loads((tmp_path / 'setup/setup.private.json').read_text(encoding='utf-8'))
    assert 'driver_result' not in state


# The planners take the identified build --------------------------------------------------------

def records():
    """Settings for the pure planners: every field reads as zero, the two calibration units full size."""
    from collections import namedtuple
    Prop = namedtuple('Prop', 'data attr')

    class Zero(dict):
        def __missing__(self, key):
            self[key] = Prop(b'\0', 0)
            return self[key]
    return [Zero({verticalpersist.SETTING: Prop(b'\0', 0)}),
            Zero({checkpoint.CP_KEYS[0]: Prop(bytes(8192), 0), checkpoint.CP_KEYS[1]: Prop(bytes(28672), 0)})]


@pytest.fixture(scope='module')
def default_install(build_fixtures):
    """The default one-click plan's inputs on the body build: FL2/FL3, the six bundled looks, the
    sound and Vertical display."""
    from desktopapp.presets import resolve
    options, selected = bundle.documents(resolve({'preset_pack': 'default-six-v1'}))
    options['vertical_persistent'] = True
    return build_fixtures.body, options, selected


def plan_counting(fixture, options, selected, *, build):
    real = buildprofile.identify
    with patch.object(buildprofile, 'identify', side_effect=real) as identify, \
            patch('looktool.nameworker.filenames', return_value=[]):
        target, _, _ = bundle.plan({'appFw.so': fixture.ap, 'cpapp-b.bin': fixture.cp}, records(), options, selected,
                                   build=build)
    return target, identify.call_count


def test_the_default_one_click_plan_identifies_nothing_when_given_the_build(default_install):
    fixture, options, selected = default_install
    target, calls = plan_counting(fixture, options, selected, build=BODY)
    assert calls == 0  # it was 14 before the planners took the build
    assert buildprofile.identify(target['appFw.so'], target['cpapp-b.bin']) is BODY


def test_a_job_session_identifies_once_for_the_default_one_click_plan(default_install):
    fixture, options, selected = default_install
    camera = GateCamera({AP: fixture.ap, CP: fixture.cp})
    real = buildprofile.identify
    with patch.object(buildprofile, 'identify', side_effect=real) as identify, \
            patch('looktool.nameworker.filenames', return_value=[]):
        programs = camera.read_programs()
        bundle.plan(programs, records(), options, selected, build=camera.require_build())
    assert identify.call_count == 1


def test_an_offline_plan_without_a_build_identifies_once(default_install):
    fixture, options, selected = default_install
    _, calls = plan_counting(fixture, options, selected, build=None)
    assert calls == 1


@pytest.mark.parametrize('mode, arguments', [
    ('fl23_enable', {}), ('sound_restore', {}), ('slot_default', {'slot': 2}), ('factory_reset', None)])
def test_direct_plan_never_identifies_when_given_the_build(build_fixtures, mode, arguments):
    from desktopapp import official
    fixture = build_fixtures.body
    if arguments is None:
        arguments = {'factory': official.load('builtin')}
    current = {'appFw.so': fixture.ap, 'cpapp-b.bin': fixture.cp}
    with patch.object(buildprofile, 'identify', side_effect=AssertionError('identified again')), \
            patch('looktool.nameworker.filenames', return_value=[]):
        direct.plan(current, records(), mode, build=BODY, **arguments)


def test_the_direct_jobs_pass_the_identified_build_to_the_bundle_planner():
    source = (ROOT / 'src/looks/looktool/direct.py').read_text(encoding='utf-8')
    calls = [node for node in ast.walk(ast.parse(source)) if isinstance(node, ast.Call)
             and isinstance(node.func, ast.Attribute) and node.func.attr == 'plan'
             and isinstance(node.func.value, ast.Name) and node.func.value.id == 'bundle']
    assert len(calls) == 3 and all(any(k.arg == 'build' for k in call.keywords) for call in calls)


def test_vertical_prepare_camera_pins_the_programs_already_read():
    sys.path.insert(0, str(ROOT / 'src/vertical'))
    from verticaltool import device
    camera = GateCamera(dict(UNKNOWN))
    camera.programs_pinned = False
    with counting() as identify, patch('looktool.device_layout.structural', return_value={'kind': 'stock'}):
        programs = camera.read_programs()
        camera.link.calls.clear()
        device.prepare_camera(camera, None, programs)
    assert [call for call in camera.link.calls if call[0] == 'read'] == []
    identify.assert_called_once()
    assert camera.programs_pinned and camera.byte_checks
