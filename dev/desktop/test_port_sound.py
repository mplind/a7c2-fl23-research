"""Shutter sound planned against the identified build, on both Sony 2.01 compiles. Offline only.

The stock boot block the sound replaces differs between builds in one instruction: its log-string
add at 0x3060a2c, because the body's .rodata from 0x4c102e0 sits 16 bytes lower. Every other sound
window, and every CP window, is the same in both builds.

Real-firmware tests read A7C2_BUILD_FIXTURES through conftest.py's build_fixtures and skip when it is
unset. The rest run everywhere on the committed regions files.
"""
from contextlib import contextmanager
import inspect
import json
from pathlib import Path
import struct
import sys
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from looktool import buildprofile, direct, firmware
from looktool.buildprofile import BUILDS, UnsupportedFirmware, identify, regions, stock
from buildfixtures import digests, manifest_digest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'src/shutter_sound'))
import boot_sound  # noqa: E402
import boot_trial  # noqa: E402
import candidate  # noqa: E402
from simbuild import CarriesBuild  # noqa: E402

PUBLIC, BODY = BUILDS
PROGRAMS = ('appFw.so', 'cpapp-b.bin')
BOOT = boot_sound.BOOT
BOOT_LOG_ADD = BOOT + 8      # `add x0,x0,#string`, after `adrp x0` at BOOT and `ldr x21` at BOOT+4
BOOT_LOG_STRING = b'Success adf_sys_get_system_sound_address'
EACH_BUILD = pytest.mark.parametrize('name, build', [('public', PUBLIC), ('body', BODY)], ids=['public', 'body'])
# A complete filter0 native-codec clip of 0xEC0 bytes, the size the CSV template names.
PAYLOAD = bytes(n % 9 for n in range(0xEC0))
# Public-build results of the shutter-sound planner at bd2132c, before the port: full-file SHA-256 of
# appFw.so and cpapp-b.bin, of each generated native header, and of the window manifest and the
# emulation report as sorted JSON. The port must not move a single public byte.
PUBLIC_BEFORE_THE_PORT = {
    'install': ('72343004541fe7830c3c9fcea1fae49c66e3eecb653c7a2c81cf31acd730f12d',
                'b8282b50609d114a86fbc061b4dc0f009dfa67cba1f48379d971666192f70fde'),
    'install-windows': '03b8cefc2f53cedeebcf5b0cbe075497b12af57954cfb3293713e32ac1cdfdaa',
    'install-program': '492aad65f6758cc5236930df593e09ce285a4c30e1123cb10d3069be7239f391',
    'install-post-probe': '12972af7baf7a7ca39d9ee5495398e9f4e0e0d02e97519836a05845d2e18a92d',
    'restore': ('2ea02f7ecbc5bb917316fe8ef4ce5ffd87eb66efaae78ba2ce11420552df539b',
                'b8282b50609d114a86fbc061b4dc0f009dfa67cba1f48379d971666192f70fde'),
    'restore-windows': '2ea02f7ecbc5bb917316fe8ef4ce5ffd87eb66efaae78ba2ce11420552df539b',
    'current-probe-stock': 'ace7d1647068bdf29b2c2ff9bd5f81974eb7aa6eaa84ff4d8334d95648a846ab',
    'current-probe-installed': '12972af7baf7a7ca39d9ee5495398e9f4e0e0d02e97519836a05845d2e18a92d',
    'emulation': 'dedfc21eae3920b3fcc13a7e2236aac8851facf804b4738fc1ff44839820b5d8',
}


@contextmanager
def offline_compiler():
    """Every native compile writes a placeholder instead of running zig. The headers are still written."""
    def compiled(source, header, path, *args, **kwargs):
        Path(path).write_bytes(b'compiled')
    with patch('looktool.nativebuild.compile_worker', side_effect=compiled):
        yield


def save(source, output, **options):
    """boot_trial.prepare, the offline plan of the Save action, on `source`."""
    with offline_compiler():
        return boot_trial.prepare(source['appFw.so'], source['cpapp-b.bin'], PAYLOAD, output, **options)


def restore_windows_inverse(ap, parts):
    """boot_trial.restore's appFw.so inverse: the saved restore windows put back, last first."""
    return boot_sound.patch(ap, boot_trial.restore_edits(parts))


def sound_restore(source):
    """The desktop's 'restore stock sound' plan (direct.plan), from current bytes only."""
    return direct.plan(source, [{}, {}], 'sound_restore')[0]


def changed_outside_regions(build, before, after):
    """The programs in which `after` differs from `before` outside the build's tool regions."""
    result = []
    for program, rows in regions(build).items():
        outside = bytearray(after[program])
        for at, raw in rows:
            outside[at:at + len(raw)] = before[program][at:at + len(raw)]
        if outside != before[program]:
            result.append(program)
    return result


def inside_one_region(build, program, at, size):
    return any(start <= at and at + size <= start + len(raw) for start, raw in regions(build)[program])


def boot_log_string(ap, add=None):
    """(address, text) of the string the stock boot block hands its logger: `adrp x0` at BOOT, then
    `add x0,x0,#imm12` at BOOT+8 (`add`, when given, in place of the one in `ap`)."""
    adrp, = struct.unpack_from('<I', ap, BOOT)
    add, = struct.unpack('<I', add or ap[BOOT_LOG_ADD:BOOT_LOG_ADD + 4])
    assert adrp & 0x9f00001f == 0x90000000, hex(adrp)    # adrp x0
    assert add & 0xffc003ff == 0x91000000, hex(add)      # add x0,x0,#imm12, unshifted
    pages = ((adrp >> 5) & 0x7ffff) << 2 | (adrp >> 29) & 3
    pages -= (pages & 1 << 20) << 1                       # sign-extend the 21-bit page delta
    at = (BOOT & ~0xfff) + (pages << 12) + ((add >> 10) & 0xfff)
    return at, ap[at:ap.index(b'\0', at)]


@pytest.fixture(scope='module')
def saves(build_fixtures, tmp_path_factory):
    """The Save action's plan on each build's stock, worked out once for the module, the build
    identified from the programs: .stock, .target, .parts and the .folder of the generated headers."""
    result = {}
    for name in ('public', 'body'):
        base = getattr(build_fixtures, name).programs
        folder = tmp_path_factory.mktemp(name) / 'save'
        target, parts = save(base, folder)
        result[name] = SimpleNamespace(stock=base, target=target, parts=parts, folder=folder)
    return result


# Real firmware -------------------------------------------------------------------------------

def test_body_sound_windows_check_body_stock(build_fixtures):
    body = build_fixtures.body.programs
    edits = boot_sound.windows(body['appFw.so'], build=BODY)
    assert edits == boot_sound.expected_windows(BODY)
    for at, old, _ in edits:
        assert body['appFw.so'][at:at + len(old)] == old, hex(at)
    assert body['appFw.so'][BOOT:BOOT + 16] == boot_sound.original_boot(BODY)
    assert boot_sound.installed(body['appFw.so'], build=BODY) is False


@pytest.mark.parametrize('name, other', [('body', PUBLIC), ('public', BODY)])
def test_each_build_is_checked_against_its_own_boot_block_only(build_fixtures, name, other, tmp_path):
    fixture = getattr(build_fixtures, name)
    with pytest.raises(ValueError, match='differs at 0x3060a24'):
        boot_sound.windows(fixture.ap, build=other)
    with pytest.raises(ValueError, match='conflict at 0x3060a24'):
        save(fixture.programs, tmp_path / 'save', build=other)
    with pytest.raises(ValueError, match='conflict at 0x3060a24'):
        boot_sound.restore_plan(fixture.ap, build=other)
    with pytest.raises(ValueError, match='conflict at 0x3060a24'), offline_compiler():
        boot_trial.current_probe(fixture.ap, tmp_path / 'probe', build=other)


def test_body_sound_new_bytes_equal_public(saves):
    """The body install writes the public install's bytes at the same offsets, and nothing else."""
    public, body = saves['public'], saves['body']
    assert body.parts['windows'] == [dict(w, before_hex=old.hex()) for w, (_, old, _) in
                                     zip(public.parts['windows'], boot_sound.expected_windows(BODY))]
    assert body.parts['cp_windows'] == public.parts['cp_windows']
    expected = {program: bytearray(data) for program, data in body.stock.items()}
    for program, key in (('appFw.so', 'windows'), ('cpapp-b.bin', 'cp_windows')):
        for window in public.parts[key]:
            at, new = window['offset'], bytes.fromhex(window['after_hex'])
            assert body.target[program][at:at + len(new)] == public.target[program][at:at + len(new)] == new
            expected[program][at:at + len(new)] = new
    assert body.target == {program: bytes(data) for program, data in expected.items()}
    # The new boot block calls the table getter and reader; it holds no data address of its own.
    assert body.target['appFw.so'][BOOT:BOOT + 16] == public.target['appFw.so'][BOOT:BOOT + 16]


def test_body_sound_restore_returns_body_stock(saves):
    body = saves['body']
    restored = sound_restore(body.target)
    assert firmware.sha(restored['appFw.so']).startswith('77fa856e')
    assert firmware.sha(restored['appFw.so']) == BODY.ap_sha256
    assert restored['appFw.so'] == body.stock['appFw.so']
    # boot_trial.restore's inverse from the job's saved windows gives the same bytes.
    assert restore_windows_inverse(body.target['appFw.so'], body.parts) == body.stock['appFw.so']
    # The electronic-only switch's own inverse returns cpapp-b.bin to body stock as well.
    switch_off = candidate.patch(restored['appFw.so'], restored['cpapp-b.bin'], restore=True)
    assert digests(switch_off) == (BODY.ap_sha256, BODY.cp_sha256)
    # The restored boot block hands its logger the body's own string again.
    assert boot_log_string(restored['appFw.so']) == (0x4c14ab3, BOOT_LOG_STRING)


@pytest.mark.parametrize('name', ['public', 'body'])
def test_restore_sound_puts_back_program_bytes_only(saves, name):
    """I-1: Restore original sound plans program bytes alone (the files it plans are the files it read),
    so the saved custom sound's files stay on the camera, unused; the English must say so."""
    from desktopapp.en import STRINGS
    installed = dict(saves[name].target)
    restored = sound_restore(installed)
    assert set(restored) == set(installed) and not any('avsystemsound' in key for key in restored)
    assert [key for key in restored if restored[key] != installed[key]] == ['appFw.so']
    english = STRINGS['改回相机原来的快门声。']
    assert 'Your saved sound stays on the camera, unused.' in english and 'Removes your saved sound' not in english
    assert english.startswith("Puts Sony’s original program bytes back")


def test_body_sound_restore_finishes_an_interrupted_install(saves):
    body = saves['body']
    partial = bytearray(body.stock['appFw.so'])
    for at, _, new in boot_sound.expected_windows(BODY)[::2]:
        partial[at:at + len(new)] = new
    target, edits = boot_sound.restore_plan(bytes(partial), build=BODY)
    assert firmware.sha(target) == BODY.ap_sha256
    assert len(edits) == len(boot_sound.expected_windows(BODY)[::2])


def test_body_boot_block_emulates_like_public(build_fixtures, saves):
    """verify_beeplist's unicorn harness runs the installed boot block through the original reader."""
    reports = {}
    for name, build in (('public', PUBLIC), ('body', BODY)):
        target, csv, edits, report = boot_sound.verify(getattr(build_fixtures, name).ap, PAYLOAD, build=build)
        assert target == saves[name].target['appFw.so']
        assert edits == boot_sound.expected_windows(build)
        reports[name] = report
    assert reports['body'] == reports['public']
    cases = {case['scenario']: case for case in reports['body']['reader_cases']}
    assert list(cases) == ['valid', 'missing', 'oversized']
    valid = cases['valid']
    assert (valid['priority'], valid['kind'], valid['bytes'], valid['filename']) == \
        (6, 3, len(PAYLOAD), '/usr/share/avsystemsound/custom-shutter.bin')
    assert not cases['missing']['output_changed'] and not cases['oversized']['output_changed']


def test_body_boot_log_add_points_at_the_same_string(build_fixtures):
    """The one data address in the sound windows: the stock boot block's log string, 16 bytes lower in
    the body's .rodata. Restoring the public add on the body would point into another string."""
    public, body = build_fixtures.public.ap, build_fixtures.body.ap
    assert boot_log_string(public) == (0x4c14ac3, BOOT_LOG_STRING)
    assert boot_log_string(body) == (0x4c14ab3, BOOT_LOG_STRING)
    for build, ap in ((PUBLIC, public), (BODY, body)):
        assert boot_log_string(ap, build.boot_log_add)[1] == BOOT_LOG_STRING
        assert ap[BOOT_LOG_ADD:BOOT_LOG_ADD + 4] == build.boot_log_add
    assert boot_log_string(body, PUBLIC.boot_log_add) == (0x4c14ac3, b'get_system_sound_address')


@EACH_BUILD
def test_sound_changes_lie_inside_the_builds_regions(saves, name, build):
    """Every byte a sound install, an interrupted install, a restore or a switch change writes lies in
    one of the build's tool regions, so the programs still identify as that build mid-job and after."""
    base, installed, parts = saves[name].stock, saves[name].target, saves[name].parts
    interrupted = dict(base, **{'appFw.so': boot_sound.patch(base['appFw.so'], boot_sound.expected_windows(build)[::2])})
    restored = sound_restore(installed)
    states = {
        'install': installed,
        'interrupted install': interrupted,
        'sound restore': restored,
        'restore from the job windows': dict(installed, **{'appFw.so': restore_windows_inverse(installed['appFw.so'], parts)}),
        'switch muted': candidate.disable(installed['appFw.so'], installed['cpapp-b.bin']),
        'switch restored': candidate.patch(restored['appFw.so'], restored['cpapp-b.bin'], restore=True),
    }
    assert installed['appFw.so'] != base['appFw.so'] and installed['cpapp-b.bin'] != base['cpapp-b.bin']
    for state, after in states.items():
        assert changed_outside_regions(build, base, after) == [], state
        assert identify(after['appFw.so'], after['cpapp-b.bin']) is build, state
    # Every window a native writer is built to rewrite lies inside one region.
    windows = [('appFw.so', w) for w in parts['windows'] + parts['restore_windows']]
    windows += [('cpapp-b.bin', w) for w in parts['cp_windows']]
    assert len(windows) == 2 * len(boot_sound.expected_windows(build)) + len(candidate.WINDOWS)
    for program, window in windows:
        size = len(bytes.fromhex(window['before_hex']))
        assert inside_one_region(build, program, window['offset'], size), (program, hex(window['offset']))


def test_body_save_recognises_its_own_result(saves):
    body = saves['body']
    assert boot_sound.installed(body.target['appFw.so'], build=BODY) is True
    target, _, edits, _ = boot_sound.plan(body.target['appFw.so'], PAYLOAD, current=True, build=BODY)
    assert (target, edits) == (body.target['appFw.so'], [])


def test_body_save_completes_an_interrupted_install(saves, tmp_path):
    body = saves['body']
    partial = dict(body.stock, **{'appFw.so': boot_sound.patch(body.stock['appFw.so'], boot_sound.expected_windows(BODY)[1::2])})
    target, parts = save(partial, tmp_path / 'save')
    assert target == body.target
    assert len(parts['windows']) == len(boot_sound.expected_windows(BODY)[::2])
    assert restore_windows_inverse(target['appFw.so'], parts) == body.stock['appFw.so']


def test_body_with_the_public_boot_block_is_refused(build_fixtures, tmp_path):
    """The 27 Oct Factory Restore wrote the public boot block into the body build. It lies inside the
    tool regions, so the programs identify as the body, but neither Save nor restore may take the
    public block for the body's own: a factory restore puts the body's back."""
    body = build_fixtures.body.programs
    assert build_fixtures.hybrid.ap[BOOT:BOOT + 16] == boot_sound.original_boot(PUBLIC)
    mixed = dict(body, **{'appFw.so': body['appFw.so'][:BOOT] + boot_sound.original_boot(PUBLIC) + body['appFw.so'][BOOT + 16:]})
    assert identify(mixed['appFw.so'], mixed['cpapp-b.bin']) is BODY
    with pytest.raises(ValueError, match='conflict at 0x3060a24'):
        save(mixed, tmp_path / 'save')
    with pytest.raises(ValueError, match='conflict at 0x3060a24'):
        sound_restore(mixed)
    with pytest.raises(ValueError, match='incomplete or different'):
        boot_sound.installed(mixed['appFw.so'], build=BODY)


def test_hybrid_programs_are_refused_before_any_sound_planning(build_fixtures, tmp_path):
    hybrid = build_fixtures.hybrid.programs
    with pytest.raises(UnsupportedFirmware):
        save(hybrid, tmp_path / 'save')
    assert not (tmp_path / 'save').exists()
    with pytest.raises(UnsupportedFirmware):
        sound_restore(hybrid)


def test_boot_sound_cli_identifies_the_build(build_fixtures, saves, tmp_path):
    payload = tmp_path / 'clip.bin'
    payload.write_bytes(PAYLOAD)
    output = tmp_path / 'candidate'
    folder = build_fixtures.body.folder
    boot_sound.main(['--ap', str(folder / 'appFw.so'), '--cp', str(folder / 'cpapp-b.bin'),
                     '--native-bin', str(payload), '--output', str(output)])
    assert (output / 'appFw.candidate.private.so').read_bytes() == saves['body'].target['appFw.so']
    windows = json.loads((output / 'windows.private.json').read_text(encoding='utf-8'))
    assert [(w['offset'], w['before_hex']) for w in windows] == \
        [(at, old.hex()) for at, old, _ in boot_sound.expected_windows(BODY)]


def test_public_sound_is_unchanged_by_the_port(build_fixtures, saves, tmp_path):
    public, save_ = build_fixtures.public.programs, saves['public']
    results = {
        'install': digests(save_.target),
        'install-windows': manifest_digest({key: save_.parts[key] for key in ('windows', 'cp_windows', 'restore_windows')}),
        'install-program': firmware.sha((save_.folder / 'program/program.private.h').read_bytes()),
        'install-post-probe': firmware.sha((save_.folder / 'post-probe.private.h').read_bytes()),
        'restore': digests(sound_restore(save_.target)),
        'restore-windows': firmware.sha(restore_windows_inverse(save_.target['appFw.so'], save_.parts)),
    }
    with offline_compiler():
        for name, ap in (('stock', public['appFw.so']), ('installed', save_.target['appFw.so'])):
            probe = boot_trial.current_probe(ap, tmp_path / name, build=PUBLIC)
            results['current-probe-' + name] = firmware.sha(probe.with_name('current-probe.private.h').read_bytes())
    results['emulation'] = manifest_digest(boot_sound.verify(public['appFw.so'], PAYLOAD, build=PUBLIC)[3])
    assert results == PUBLIC_BEFORE_THE_PORT


# Committed tables ----------------------------------------------------------------------------

@pytest.mark.parametrize('build', BUILDS, ids=[build.key for build in BUILDS])
def test_original_boot_is_the_builds_stock_boot_block(build):
    original = boot_sound.original_boot(build)
    assert len(original) == 16
    assert original[8:12] == build.boot_log_add
    assert stock(build, 'appFw.so', BOOT, 16) == original


@pytest.mark.parametrize('build', BUILDS, ids=[build.key for build in BUILDS])
def test_every_sound_window_holds_the_builds_stock(build):
    edits = boot_sound.expected_windows(build)
    assert edits[-1][0] == BOOT    # the boot call is enabled last and removed first
    for at, old, new in edits:
        assert len(old) == len(new), hex(at)
        assert stock(build, 'appFw.so', at, len(old)) == old, hex(at)
    for at, before, _ in candidate.WINDOWS:
        assert stock(build, 'cpapp-b.bin', at, len(before)) == before, hex(at)


def test_body_windows_differ_from_public_only_at_the_boot_log_add():
    public, body = boot_sound.expected_windows(PUBLIC), boot_sound.expected_windows(BODY)
    assert [(at, new) for at, _, new in body] == [(at, new) for at, _, new in public]
    differing = {at + i for (at, old, _), (_, other, _) in zip(public, body)
                 for i, (a, b) in enumerate(zip(old, other)) if a != b}
    assert differing and all(BOOT_LOG_ADD <= at < BOOT_LOG_ADD + 4 for at in differing)


@pytest.mark.parametrize('function', ['windows', 'installed', 'restore_plan', 'plan', 'verify'])
def test_sound_planners_require_the_build_as_a_keyword(function):
    parameter = inspect.signature(getattr(boot_sound, function)).parameters['build']
    assert parameter.kind is inspect.Parameter.KEYWORD_ONLY and parameter.default is inspect.Parameter.empty


@pytest.mark.parametrize('function', ['original_boot', 'expected_windows'])
def test_sound_tables_take_the_build(function):
    assert list(inspect.signature(getattr(boot_sound, function)).parameters) == ['build']


def test_save_identifies_the_build_unless_given_and_probe_requires_it():
    prepare = inspect.signature(boot_trial.prepare).parameters['build']
    assert prepare.kind is inspect.Parameter.KEYWORD_ONLY and prepare.default is None
    probe = inspect.signature(boot_trial.current_probe).parameters['build']
    assert probe.kind is inspect.Parameter.KEYWORD_ONLY and probe.default is inspect.Parameter.empty


def test_unidentified_programs_are_refused_before_any_sound_planning(tmp_path):
    stand_in = {'appFw.so': b'stand-in appFw.so', 'cpapp-b.bin': b'stand-in cpapp-b.bin'}
    with pytest.raises(UnsupportedFirmware):
        save(stand_in, tmp_path / 'save')
    assert not (tmp_path / 'save').exists()
    with pytest.raises(UnsupportedFirmware):
        sound_restore(stand_in)


def stand_in_ap(build, installed=False):
    """A stand-in appFw.so holding the build's sound windows, stock or installed, and nothing else."""
    edits = boot_sound.expected_windows(build)
    ap = bytearray(max(at + len(old) for at, old, _ in edits) + 8)
    for at, old, new in edits:
        ap[at:at + len(old)] = new if installed else old
    return bytes(ap)


@pytest.mark.parametrize('build', BUILDS, ids=[build.key for build in BUILDS])
def test_desktop_sound_restore_uses_the_identified_build(build):
    current = {'appFw.so': stand_in_ap(build, installed=True), 'cpapp-b.bin': b'stand-in cpapp-b.bin'}
    with patch.object(buildprofile, 'identify', return_value=build) as identified:
        assert sound_restore(current)['appFw.so'] == stand_in_ap(build)
    identified.assert_called_once_with(current['appFw.so'], current['cpapp-b.bin'])


class SoundCamera(CarriesBuild):
    """A camera for the read-only current-sound check whose program files are stand-ins."""
    identity = dict(model='ILCE-7CM2', serial_sha256='fixture')
    def __enter__(self): return self
    def __exit__(self, *args): return False
    def read(self, path, missing=False): return None if missing else b'current program'
    def temp_read(self, name, missing=False): return None


@pytest.mark.parametrize('build', BUILDS, ids=[build.key for build in BUILDS])
def test_current_sound_check_uses_the_cameras_identified_build(build, tmp_path):
    from desktopapp.actions import sound_state
    camera = SoundCamera()
    camera.carries = build
    probe = tmp_path / 'probe'
    probe.write_bytes(b'read-only probe')
    with patch('trial.factory', return_value=camera), patch('candidate.is_enabled', return_value=False), \
         patch('candidate.guard'), patch('candidate.require_registry'), \
         patch('boot_sound.installed', return_value=False) as installed, \
         patch('boot_trial.current_probe', return_value=probe) as current_probe, \
         patch('looktool.devicesession.invoke', return_value={}):
        sound_state.verify(dict(workspace=str(tmp_path / 'sound'), accepted=False), tmp_path)
    assert camera.firmware_build is build
    assert installed.call_args.kwargs == {'build': build}
    assert current_probe.call_args.kwargs == {'build': build}


def test_current_sound_check_refuses_unidentified_programs(tmp_path):
    from desktopapp.actions import sound_state
    camera = SoundCamera()
    camera.carries = None    # the real identification, which refuses stand-in programs
    with patch('trial.factory', return_value=camera), \
         patch('boot_trial.current_probe', side_effect=AssertionError('probe built')), \
         patch('looktool.devicesession.invoke', side_effect=AssertionError('probe run')), \
         pytest.raises(UnsupportedFirmware):
        sound_state.verify(dict(workspace=str(tmp_path / 'sound'), accepted=False), tmp_path)
