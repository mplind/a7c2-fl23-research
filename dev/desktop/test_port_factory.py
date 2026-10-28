"""Factory Restore per build: a camera is restored only from its own build's stock regions.

On 27 Oct 2026 a Factory Restore wrote the public build's regions file into the body build, 14 bytes
in three windows, which camera-check/putback.py put back on 28 Oct. Now the built-in reference is
chosen once the camera's programs are identified, a full Sony reference is used only on the build its
own programs are, and a job's verification reloads the reference of the build it recorded.

Cameras are simulated (test_checkpoint.Camera). Real-firmware tests read A7C2_BUILD_FIXTURES through
conftest.py's build_fixtures and skip when it is unset; the rest run everywhere on the committed
regions files. Offline only.
"""
import copy
import hashlib
import inspect
import json
import os
from pathlib import Path
import tempfile
from unittest.mock import patch

import pytest

from desktopapp import official, worker
from looktool import buildprofile, checkpoint, checkpointworker, direct, nameworker
from looktool.buildprofile import BUILDS, UnsupportedFirmware, identity_regions, regions
import buildfixtures
from test_checkpoint import Camera, fake_compile, stock_names
from test_device_job import Prop
from test_direct import SimDirect
from test_language import finish_failed_job
from guihelpers import HAN

PUBLIC, BODY = BUILDS
PROGRAMS = ('appFw.so', 'cpapp-b.bin')
# The 28 Oct put-back (camera-check/putback.py, RESTORED): (offset, what the 27 Oct restore wrote,
# the body's own bytes). 2 + 1 + 11 = 14 bytes; cpapp-b.bin was untouched.
PUT_BACK = [(0x3060a2d, '0c2b', 'cc2a'),
            (0x3528811, 'f0', 'b0'),
            (0x4c7cf7c, '1200020406080a0c0e1000', '06080a0c0e10121416181a')]
# The public table's 12 bytes, which lie outside every body region: the body's table sits at 0x4c7cf6c.
PUBLIC_TABLE = range(0x4c7cf7c, 0x4c7cf88)
CP_SIZES = {0x02a40001: 8192, 0x02a4000d: 28672}
SELECTION = 0x02cf0cbb  # the current Creative Look selection the factory plan resets
# Public-build Factory Restore at 0cea304, before this task: target SHA-256 (appFw.so, cpapp-b.bin),
# the reset settings as sorted JSON, and the native program headers it writes, for a public camera with
# every restore region changed, one with Vertical Display installed, and one with a Vertical Display
# window holding a byte that is neither stock nor installed. The last tells the restore set from the
# identity set: Factory Restore writes only the restore set (R29), so it leaves that byte, which the
# vertical stage doesn't recognise as installed. The port must not move a single public byte.
PUBLIC_BEFORE_THE_PORT = {
    'vertical-window-stray-byte': {
        'target': ('8f66278104bf976796e533c2cca1d243875c3ca592f807f83fa1b16221b77996',
                   buildfixtures.FINDINGS['public-2.01'][1]),
        'wanted': '96a23ed45d0720bf6fde3f815446960164ad550c05b65f4f9fe4728e3616dfe6',
        'headers': 'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855', 'windows': 0},
    'every-region-changed': {
        'target': buildfixtures.FINDINGS['public-2.01'],
        'wanted': '96a23ed45d0720bf6fde3f815446960164ad550c05b65f4f9fe4728e3616dfe6',
        'headers': 'c4034c3a404ee1ee860c2c760754e22827df8240e48550781f5d860a278cf024', 'windows': 60},
    'vertical-installed': {
        'target': buildfixtures.FINDINGS['public-2.01'],
        'wanted': '96a23ed45d0720bf6fde3f815446960164ad550c05b65f4f9fe4728e3616dfe6',
        'headers': '98874040e41fffb0032d97bc58aac494f47e875452f8037bfc86a063c274a5d8', 'windows': 20},
}


def sha(data):
    return hashlib.sha256(data).hexdigest()


def programs(fixture):
    return {'appFw.so': fixture.ap, 'cpapp-b.bin': fixture.cp}


def digests(values):
    return sha(values['appFw.so']), sha(values['cpapp-b.bin'])


def windows(before, after):
    """Every run of consecutive differing bytes of two equal-length files: (offset, before hex, after hex)."""
    assert len(before) == len(after)
    step, rows = 1 << 16, []
    for block in range(0, len(before), step):
        if before[block:block + step] == after[block:block + step]:
            continue
        for at in range(block, min(block + step, len(before))):
            if before[at] != after[at]:
                if rows and rows[-1][0] + len(rows[-1][1]) == at:
                    rows[-1][1].append(before[at])
                    rows[-1][2].append(after[at])
                else:
                    rows.append((at, bytearray([before[at]]), bytearray([after[at]])))
    return [(at, old.hex(), new.hex()) for at, old, new in rows]


def with_regions(data, rows):
    """`data` with each (offset, bytes) of `rows` written over it."""
    result = bytearray(data)
    for at, raw in rows:
        result[at:at + len(raw)] = raw
    return bytes(result)


def every_region_changed(values, build):
    """A `build` camera on which tools have changed every byte of every restore region."""
    return {name: with_regions(values[name], [(at, bytes(b ^ 0x5a for b in raw)) for at, raw in rows])
            for name, rows in regions(build).items()}


def inside(at, rows):
    return any(start <= at < start + len(raw) for start, raw in rows)


def current(values):
    return dict(values, **{'resources/' + name: stock_names() for name in nameworker.filenames()})


def factory_records():
    """Settings for the pure planner: the two calibration units the factory plan reads."""
    return [{}, {key: Prop(bytes(size), 0) for key, size in CP_SIZES.items()}]


def settings(ap):
    """Saved and live settings with FL2 selected: every look field a factory reset puts back, plus the
    two calibration units."""
    fields = dict(direct.recipe_defaults(ap, range(1, 7)))
    fields.update({key: b'\x0a' for key in (*checkpoint.AP_KEYS, SELECTION)})
    return json.dumps([{str(key): [value.hex(), 0] for key, value in fields.items()},
                       {str(key): [bytes(size).hex(), 0] for key, size in CP_SIZES.items()}]).encode()


def camera(values):
    """A simulated camera holding real program files, identified for real (not a carried build)."""
    raw = settings(values['appFw.so'])
    sim = Camera(dict(current(values), **{'settings-ram.bin': raw, 'settings-saved.bin': raw}))
    sim.carries = None
    return sim


def unchanged(sim):
    return copy.deepcopy((sim.files, sim.ram, sim.saved))


def assert_nothing_written(sim, before):
    assert sim.native_calls == [] and sim.saves == []
    assert (sim.files, sim.ram, sim.saved) == before


def through_the_worker(action, sim, folder, monkeypatch, **arguments):
    """Run a desktop direct action the way the Factory Restore button does, on simulated camera `sim`."""
    monkeypatch.setenv('A7C2_DESKTOP_DATA', str(folder / 'data'))
    job = folder / ('job-' + action)
    job.mkdir(parents=True, exist_ok=True)
    arguments = dict(dict(workspace=str(folder / 'reset'), firmware='2.01', power_confirmed=True), **arguments)
    with patch('looktool.direct.DirectJob', side_effect=lambda root: SimDirect(root, factory=lambda expected=None: sim)), \
         patch.object(checkpointworker, 'compile_worker', side_effect=fake_compile):
        return worker.run(action, arguments, job)


def full_reference(folder, fixture):
    """A prepared full Sony 2.01 reference (official.prepare's layout) holding `fixture`'s program files.
    Its CX89700_ALLLANG.bin is a stand-in of Sony's size: the refusals come before it is read."""
    folder.mkdir()
    for name in PROGRAMS:
        (folder / name).symlink_to(fixture.folder / name)
    (folder / 'CX89700_ALLLANG.bin').write_bytes(bytes(2390264))
    sizes = {name: (folder / name).stat().st_size for name in official.FILES}
    (folder / 'reference.json').write_text(json.dumps({'model_code': official.MODEL, 'version': '2.01',
                                                       'decoder': 'test', 'sizes': sizes}), encoding='utf-8')
    return folder


def put_back_reference(values):
    """The 28 Oct put-back's reference (camera-check/putback.py build_reference): the public regions
    file's regions, each holding the body's own bytes at the same offset, recorded as the body build."""
    document = json.loads((buildprofile.ASSETS / PUBLIC.regions_file).read_text(encoding='utf-8'))
    for name in PROGRAMS:
        for region in document['programs'][name]['regions']:
            at, size = region['offset'], region['bytes']
            region['zlib_base64'] = buildprofile.encode(values[name][at:at + size])
    document['firmware_build'] = BODY.key
    return document


# The built-in references -----------------------------------------------------------------------

@pytest.mark.parametrize('build', BUILDS, ids=[build.key for build in BUILDS])
def test_builtin_is_the_builds_own_restore_set(build):
    document = official.builtin(build)
    assert document['firmware_build'] == build.key
    stored = json.loads((buildprofile.ASSETS / build.regions_file).read_text(encoding='utf-8'))
    assert {key: value for key, value in document.items() if key != 'firmware_build'} == stored
    # R29: Factory Restore writes the restore set (the regions file), not the wider identity set.
    decoded = buildprofile.decode(document, build, build.regions_file)
    assert decoded == regions(build)
    assert len(identity_regions(build)['appFw.so']) > len(decoded['appFw.so'])


def test_the_builtin_reference_is_chosen_after_identification():
    reference = official.load('builtin')
    assert reference == {'builtin': {build.key: official.builtin(build) for build in BUILDS}}
    for build in BUILDS:
        assert direct.factory_reference(reference, build) == official.builtin(build)


@pytest.mark.parametrize('camera_build, reference_build', [(BODY, PUBLIC), (PUBLIC, BODY)], ids=['body', 'public'])
def test_a_reference_of_another_build_is_refused_before_planning(camera_build, reference_build):
    ap, cp = bytes(camera_build.ap_bytes), bytes(camera_build.cp_bytes)
    refused = buildprofile.REFERENCE_OTHER_BUILD % (reference_build.key, camera_build.key)
    full = {'appFw.so': ap, 'cpapp-b.bin': cp, 'CX89700_ALLLANG.bin': b'', 'firmware_build': reference_build.key}
    for reference in (official.builtin(reference_build), full):
        # No settings at all: planning would fail on them, so the refusal comes first.
        with pytest.raises(buildprofile.OtherBuild) as error:
            direct.plan({'appFw.so': ap, 'cpapp-b.bin': cp}, None, 'factory_reset', factory=reference, build=camera_build)
        assert str(error.value) == refused


def test_a_reference_without_a_recorded_build_is_refused():
    document = official.builtin(PUBLIC)
    del document['firmware_build']
    for reference in (document, {'appFw.so': b'', 'cpapp-b.bin': b'', 'CX89700_ALLLANG.bin': b''}):
        with pytest.raises(ValueError, match='records no firmware build'):
            direct.factory_reference(reference, PUBLIC)
    with pytest.raises(ValueError, match='No built-in factory reference for body-2.01-20250923'):
        direct.factory_reference({'builtin': {PUBLIC.key: official.builtin(PUBLIC)}}, BODY)


def damaged(change):
    document = official.builtin(PUBLIC)
    change(document['programs']['appFw.so']['regions'], document)
    return document


def swap_first_two(rows, _):
    rows[0], rows[1] = rows[1], rows[0]


def overlap_the_next(rows, _):
    rows[1]['offset'] = rows[0]['offset'] + rows[0]['bytes'] - 1


def loose_base64(rows, _):
    rows[0]['zlib_base64'] = rows[0]['zlib_base64'][:4] + '\n' + rows[0]['zlib_base64'][4:]


def float_offset(rows, _):
    rows[0]['offset'] = float(rows[0]['offset'])


def bool_size(rows, _):
    rows[0]['bytes'] = True


def short_region(rows, _):
    rows[0]['bytes'] += 1


def damaged_colour_unit(_, document):
    unit = next(iter(document['color_units'].values()))[0]
    unit['zlib_base64'] = '!' + unit['zlib_base64'][1:]


def missing_colour_unit(_, document):
    next(iter(document['color_units'].values())).pop()


@pytest.mark.parametrize('change', [swap_first_two, overlap_the_next, loose_base64, float_offset, bool_size,
                                    short_region, damaged_colour_unit, missing_colour_unit])
def test_regional_references_are_decoded_by_buildprofile(change):
    """Task 1 minor 3: the factory plan decodes a regional reference with buildprofile's own checks
    (file order, no overlap, strict base64, integer offsets and sizes, stated sizes, every colour unit)."""
    values = current({'appFw.so': bytes(PUBLIC.ap_bytes), 'cpapp-b.bin': bytes(PUBLIC.cp_bytes)})
    # Control: an undamaged reference is decoded, and planning these stand-ins then fails on their look descriptors.
    with pytest.raises(ValueError, match='Creative Look descriptor differs'):
        direct.plan(values, factory_records(), 'factory_reset', factory=official.builtin(PUBLIC), build=PUBLIC)
    with pytest.raises(ValueError, match='Original reference'):
        direct.plan(values, factory_records(), 'factory_reset', factory=damaged(change), build=PUBLIC)


def test_direct_has_no_region_decoder_of_its_own():
    source = inspect.getsource(direct)
    assert 'b64decode' not in source and 'decompress' not in source


# Real program files ----------------------------------------------------------------------------

def test_builtin_factory_on_body_writes_only_body_stock(build_fixtures, tmp_path, monkeypatch):
    """Replays 27 Oct: Factory Restore with the built-in reference, from the Factory Restore button, on
    the body camera in the state that restore found (stock programs, FL2 selected)."""
    body = programs(build_fixtures.body)
    # What the 27 Oct restore wrote: the public regions file over the body's programs.
    wrote = {name: with_regions(body[name], rows) for name, rows in regions(PUBLIC).items()}
    assert digests(wrote) == buildfixtures.HYBRID
    sim = camera(body)
    result = through_the_worker('direct_factory_reset', sim, tmp_path, monkeypatch)
    state = json.loads((Path(result['workspace']) / 'direct.private.json').read_text(encoding='utf-8'))
    assert state['firmware_build'] == BODY.key and state['factory_path'] == 'builtin'
    # The body's own stock is already there: no program byte is written, only the look settings.
    restored = {name: sim.files[path] for name, path in checkpoint.PROGRAM_PATHS.items()}
    assert digests(restored) == buildfixtures.FINDINGS[BODY.key]
    assert state['program_builds'] == [] and ('program', 1) not in sim.native_calls
    # And between what 27 Oct wrote and what this restore leaves lies exactly the put-back.
    assert windows(wrote['appFw.so'], restored['appFw.so']) == PUT_BACK
    assert sum(len(old) // 2 for _, old, _ in PUT_BACK) == 14
    assert wrote['cpapp-b.bin'] == restored['cpapp-b.bin']


def test_body_restore_writes_every_changed_region_back_with_body_stock(build_fixtures, tmp_path, monkeypatch):
    body = programs(build_fixtures.body)
    before = every_region_changed(body, BODY)
    sim = camera(before)
    result = through_the_worker('direct_factory_reset', sim, tmp_path, monkeypatch)
    assert result['phase'] == 'AWAITING_RELOAD'
    after = {name: sim.files[path] for name, path in checkpoint.PROGRAM_PATHS.items()}
    assert digests(after) == buildfixtures.FINDINGS[BODY.key]
    for name, rows in regions(BODY).items():
        for at, old, new in windows(before[name], after[name]):
            assert all(inside(offset, rows) for offset in range(at, at + len(old) // 2)), (name, hex(at))
    assert all(before['appFw.so'][at] == after['appFw.so'][at] for at in PUBLIC_TABLE)


def test_the_27_oct_state_is_refused_before_any_write(build_fixtures, tmp_path, monkeypatch):
    sim = camera(programs(build_fixtures.hybrid))
    before = unchanged(sim)
    with pytest.raises(UnsupportedFirmware):
        through_the_worker('direct_factory_reset', sim, tmp_path, monkeypatch)
    assert_nothing_written(sim, before)


def test_body_regions_alone_cannot_repair_the_27_oct_state(build_fixtures):
    """Why the identity gate refuses the 27 Oct state: the public table landed outside every body
    region, so the body's own regions file leaves those 11 bytes as the public restore wrote them."""
    body, hybrid = programs(build_fixtures.body), programs(build_fixtures.hybrid)
    repaired = with_regions(hybrid['appFw.so'], regions(BODY)['appFw.so'])
    assert windows(repaired, body['appFw.so']) == [PUT_BACK[2]]


def test_the_27_oct_state_is_recovered_by_the_put_back_reference(build_fixtures):
    """The recovery for a body camera in the 27 Oct state, which Factory Restore refuses: the regional
    factory plan computed directly, for the body build, from the put-back's own reference (the public
    region offsets holding the body's bytes), as camera-check/putback.py ran it on 28 Oct."""
    body, hybrid = programs(build_fixtures.body), programs(build_fixtures.hybrid)
    with pytest.raises(UnsupportedFirmware):
        buildprofile.identify(hybrid['appFw.so'], hybrid['cpapp-b.bin'])
    target, _, rename = direct.plan(current(hybrid), factory_records(), 'factory_reset',
                                    factory=put_back_reference(body), build=BODY)
    assert digests(target) == buildfixtures.FINDINGS[BODY.key]
    assert windows(hybrid['appFw.so'], target['appFw.so']) == [(at, new, old) for at, new, old in PUT_BACK]
    assert target['cpapp-b.bin'] == hybrid['cpapp-b.bin'] and rename is None
    assert all(target['resources/' + name] == stock_names() for name in nameworker.filenames())


def test_full_reference_of_another_build_is_refused(build_fixtures, tmp_path, monkeypatch):
    """A full Sony 2.01 reference records the build its own programs are; the public BODYDATA cache
    is refused on a body camera before anything is planned, and a body full reference on a public one."""
    public = official.load(full_reference(tmp_path / 'public-reference', build_fixtures.public))
    assert public['firmware_build'] == PUBLIC.key
    body = official.load(full_reference(tmp_path / 'body-reference', build_fixtures.body))
    assert body['firmware_build'] == BODY.key
    for build, fixture, reference in ((BODY, build_fixtures.body, 'public-reference'),
                                      (PUBLIC, build_fixtures.public, 'body-reference')):
        sim = camera(programs(fixture))
        before = unchanged(sim)
        other = {'public-reference': PUBLIC, 'body-reference': BODY}[reference]
        with patch.object(checkpointworker, 'build_programs', side_effect=AssertionError('planned')), \
             pytest.raises(buildprofile.OtherBuild) as error:
            through_the_worker('direct_factory_reset', sim, tmp_path / build.key, monkeypatch,
                               factory=str(tmp_path / reference))
        assert str(error.value) == buildprofile.REFERENCE_OTHER_BUILD % (other.key, build.key)
        assert_nothing_written(sim, before)


def test_a_full_reference_of_no_supported_build_is_refused_when_loaded(build_fixtures, tmp_path):
    with pytest.raises(buildprofile.OtherBuild) as error:
        official.load(full_reference(tmp_path / 'hybrid-reference', build_fixtures.hybrid))
    assert str(error.value) == buildprofile.REFERENCE_UNSUPPORTED


@pytest.mark.skipif(not os.environ.get('A7C2_ORIGINAL_REFERENCE'),
                    reason='A7C2_ORIGINAL_REFERENCE (a prepared Sony 2.01 BODYDATA cache) is not set')
def test_the_decoded_public_bodydata_is_a_public_reference(build_fixtures):
    reference = official.load(os.environ['A7C2_ORIGINAL_REFERENCE'])
    assert reference['firmware_build'] == PUBLIC.key
    assert digests(reference) == buildfixtures.FINDINGS[PUBLIC.key]
    body = current(programs(build_fixtures.body))
    with pytest.raises(buildprofile.OtherBuild):
        direct.plan(body, None, 'factory_reset', factory=reference, build=BODY)
    changed = current(every_region_changed(programs(build_fixtures.public), PUBLIC))
    target, _, _ = direct.plan(changed, factory_records(), 'factory_reset', factory=reference)
    assert digests(target) == buildfixtures.FINDINGS[PUBLIC.key]


def test_verify_uses_the_jobs_recorded_build(build_fixtures, tmp_path, monkeypatch):
    sim = camera(every_region_changed(programs(build_fixtures.body), BODY))
    result = through_the_worker('direct_factory_reset', sim, tmp_path, monkeypatch)
    state_path = Path(result['workspace']) / 'direct.private.json'
    assert json.loads(state_path.read_text(encoding='utf-8'))['firmware_build'] == BODY.key
    sim.boot = 'test-boot-2'  # the cold restart
    # The public reference would plan the 27 Oct bytes and fail the readback: verified means body.
    with patch.object(direct, 'plan', wraps=direct.plan) as planned:
        verified = through_the_worker('direct_verify', sim, tmp_path, monkeypatch)
    assert verified['phase'] == 'LOADED'
    assert planned.call_args.kwargs['build'] is BODY
    # A job recorded on the body build never verifies another build's camera.
    state = json.loads(state_path.read_text(encoding='utf-8'))
    state_path.write_text(json.dumps(dict(state, phase='AWAITING_RELOAD')), encoding='utf-8')
    for name, path in checkpoint.PROGRAM_PATHS.items():
        sim.files[path] = programs(build_fixtures.public)[name]
    sim.native_calls.clear()
    sim.saves.clear()
    before = unchanged(sim)
    with pytest.raises(direct.ContentChanged) as error:
        through_the_worker('direct_verify', sim, tmp_path, monkeypatch)
    assert str(error.value) == buildprofile.JOB_OTHER_BUILD % (BODY.key, PUBLIC.key)
    assert_nothing_written(sim, before)


def test_a_job_saved_before_builds_were_recorded_verifies_the_cameras_build(build_fixtures, tmp_path, monkeypatch):
    sim = camera(every_region_changed(programs(build_fixtures.body), BODY))
    result = through_the_worker('direct_factory_reset', sim, tmp_path, monkeypatch)
    state_path = Path(result['workspace']) / 'direct.private.json'
    state = json.loads(state_path.read_text(encoding='utf-8'))
    del state['firmware_build']
    state_path.write_text(json.dumps(state), encoding='utf-8')
    sim.boot = 'test-boot-2'
    assert through_the_worker('direct_verify', sim, tmp_path, monkeypatch)['phase'] == 'LOADED'


def public_factory_outputs(values):
    """The public Factory Restore of `values`: target digests, reset settings and written headers."""
    reference = official.load('builtin')
    target, wanted, rename = direct.plan(current(values), factory_records(), 'factory_reset', factory=reference)
    assert rename is None
    with tempfile.TemporaryDirectory() as folder, \
         patch.object(checkpointworker, 'compile_worker', side_effect=fake_compile):
        builds = checkpointworker.build_programs(current(values), target, Path(folder), None,
                                                 window_priority=lambda row: (row[0], row[1]))
        headers = b''.join(Path(build['path']).with_suffix('.private.h').read_bytes() for build in builds)
    return {'target': digests(target),
            'wanted': sha(json.dumps([{hex(key): value.hex() for key, value in sorted(fields.items())}
                                      for fields in wanted], sort_keys=True).encode()),
            'headers': sha(headers), 'windows': sum(build['windows'] for build in builds)}


def stray_vertical_byte(values, portraitlayout):
    """`values` with the first Vertical Display window's first byte neither stock nor installed."""
    at, raw = buildprofile.vertical_display_windows()[0]
    installed = portraitlayout.references(values['appFw.so'], True)[0][at:at + len(raw)]
    ap = bytearray(values['appFw.so'])
    ap[at] = next(value for value in range(256) if value not in (raw[0], installed[0]))
    assert not portraitlayout.active(bytes(ap)) and not inside(at, regions(PUBLIC)['appFw.so'])
    assert buildprofile.identify(bytes(ap), values['cpapp-b.bin']) is PUBLIC
    return dict(values, **{'appFw.so': bytes(ap)})


def test_public_factory_restore_is_unchanged_by_the_port(build_fixtures):
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'src/vertical'))
    from verticaltool import portraitlayout
    public = programs(build_fixtures.public)
    results = {'vertical-window-stray-byte': public_factory_outputs(stray_vertical_byte(public, portraitlayout)),
               'every-region-changed': public_factory_outputs(every_region_changed(public, PUBLIC)),
               'vertical-installed': public_factory_outputs(
                   dict(public, **{'appFw.so': portraitlayout.references(public['appFw.so'], True)[0]}))}
    assert results == PUBLIC_BEFORE_THE_PORT


# The refusals, in English ----------------------------------------------------------------------

@pytest.mark.parametrize('template, values, english', [
    ('REFERENCE_OTHER_BUILD', ('public-2.01', 'body-2.01-20250923'),
     'The selected Sony firmware file is build public-2.01, but the camera is body-2.01-20250923. Nothing was written'),
    ('REFERENCE_UNSUPPORTED', (), "The selected Sony firmware file isn't a supported firmware build, so nothing was written"),
    ('JOB_OTHER_BUILD', ('body-2.01-20250923', 'public-2.01'),
     'This job recorded firmware build body-2.01-20250923, but the camera is now public-2.01. Nothing was verified or written'),
])
def test_factory_refusals_are_shown_in_english(window, tmp_path, template, values, english):
    error = getattr(buildprofile, template) % values if values else getattr(buildprofile, template)
    text = finish_failed_job(window(language='en'), tmp_path, error)
    assert text == 'Operation stopped: ' + english + '. Please export diagnostics.'
    assert not HAN.search(text)
