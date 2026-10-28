"""Which Sony compile of ILCE-7CM2 2.01 a camera's program files are. Offline only.

Real-firmware tests read the folder named by A7C2_BUILD_FIXTURES through conftest.py's build_fixtures
(see buildfixtures.py). They skip when the variable is unset and fail when it is set but a file isn't
the one the 28 Oct findings recorded.
Synthetic tests run everywhere on two 64 KiB builds shaped like those two.
"""
import inspect
import json
from pathlib import Path
import random
from types import SimpleNamespace

import pytest

from buildfixtures import DIGESTS, FINDINGS, PROGRAMS, SIZES, sha
from looktool.buildprofile import BUILDS, Build, UnsupportedFirmware, identify, regions, stock, translate
from looktool import buildprofile
import build_body_reference

ROOT = Path(__file__).resolve().parents[2]
ASSETS = ROOT / 'src/looks/assets'
STOCK_TABLE = bytes.fromhex('1200020406080a0c0e100000')
PUBLIC, BODY = BUILDS
EACH_BUILD = pytest.mark.parametrize('name, key', [('public', 'public-2.01'), ('body', 'body-2.01-20250923')])


def public_reference():
    return json.loads((ASSETS / PUBLIC.regions_file).read_text(encoding='utf-8'))


# Real firmware -------------------------------------------------------------------------------

def test_fixture_hashes_match_findings(build_fixture_files):
    for name, digests in DIGESTS.items():
        assert build_fixture_files[name].digests == digests, name
        assert (len(build_fixture_files[name].ap), len(build_fixture_files[name].cp)) == SIZES, name


def test_public_and_body_fixtures_identify(build_fixtures):
    assert identify(build_fixtures.public.ap, build_fixtures.public.cp).key == 'public-2.01'
    assert identify(build_fixtures.body.ap, build_fixtures.body.cp).key == 'body-2.01-20250923'


@pytest.mark.parametrize('program, offset', [('appFw.so', 0x100000), ('cpapp-b.bin', 0x400000)])
def test_one_byte_outside_the_regions_is_unsupported(build_fixtures, program, offset):
    files = {'appFw.so': bytearray(build_fixtures.body.ap), 'cpapp-b.bin': bytearray(build_fixtures.body.cp)}
    files[program][offset] ^= 1
    with pytest.raises(UnsupportedFirmware):
        identify(bytes(files['appFw.so']), bytes(files['cpapp-b.bin']))


def test_the_27_oct_hybrid_is_refused(build_fixtures):
    # public table bytes landed at 0x4c7cf7c, outside the body build's regions: never write to this
    hybrid, public, body = build_fixtures.hybrid.ap, build_fixtures.public.ap, build_fixtures.body.ap
    assert hybrid[0x4c7cf7c:0x4c7cf88] == public[0x4c7cf7c:0x4c7cf88] != body[0x4c7cf7c:0x4c7cf88]
    with pytest.raises(UnsupportedFirmware):
        identify(build_fixtures.hybrid.ap, build_fixtures.hybrid.cp)


def test_programs_from_two_builds_are_refused(build_fixtures):
    with pytest.raises(UnsupportedFirmware):
        identify(build_fixtures.public.ap, build_fixtures.body.cp)
    with pytest.raises(UnsupportedFirmware):
        identify(build_fixtures.body.ap, build_fixtures.public.cp)


@EACH_BUILD
def test_partially_written_regions_still_identify(build_fixtures, name, key):
    """An interrupted FL2/FL3 install: every other write landed. Resume and restore still need the build."""
    programs = getattr(build_fixtures, name)
    manifest = json.loads((ROOT / 'src/camera_runtime/assets/patches.json').read_text(encoding='utf-8'))
    written = []
    for source, spec in zip((programs.ap, programs.cp), manifest):
        result = bytearray(source)
        for write in spec['writes'][::2]:
            at, after = int(write['file_offset'], 16), bytes.fromhex(write['after_hex'])
            result[at:at + len(after)] = after
        written.append(bytes(result))
    assert sha(written[0]) != programs.digests[0] and sha(written[1]) != programs.digests[1]
    assert identify(*written).key == key


@EACH_BUILD
def test_legacy_converter_identifies_its_build(build_fixtures, name, key):
    """Leftovers of an older tool release still identify, so Factory Restore can clean them."""
    from looktool.devicesession import modules
    modules()
    import compat
    programs = getattr(build_fixtures, name)
    ap = bytearray(programs.ap)
    ap[0x3528804:0x3528804 + len(compat.LEGACY_CONVERTER)] = compat.LEGACY_CONVERTER
    assert bytes(ap) != programs.ap
    assert identify(bytes(ap), programs.cp).key == key


def test_regions_hold_each_builds_own_stock_bytes(build_fixtures):
    for build, programs in ((PUBLIC, build_fixtures.public), (BODY, build_fixtures.body)):
        files = dict(zip(PROGRAMS, (programs.ap, programs.cp)))
        for program, rows in regions(build).items():
            for at, raw in rows:
                assert files[program][at:at + len(raw)] == raw, (build.key, program, hex(at))


def test_translated_table_addresses_hold_the_same_bytes(build_fixtures):
    """The body's .rodata after 0x4c102e0 sits 16 bytes earlier, the look table included."""
    for offset in range(0x4c7cf7c, 0x4c7cf89):
        assert build_fixtures.body.ap[translate(offset, BODY)] == build_fixtures.public.ap[offset], hex(offset)


def test_committed_body_reference_is_what_the_script_produces(build_fixtures, tmp_path):
    output = tmp_path / 'body.json'
    build_body_reference.main(['--components', str(build_fixtures.body.folder), '--output', str(output)])
    assert output.read_bytes() == (ASSETS / BODY.regions_file).read_bytes()


@pytest.mark.parametrize('name', ['public', 'hybrid'])
def test_body_reference_is_built_only_from_body_programs(build_fixtures, name):
    programs = getattr(build_fixtures, name)
    public = public_reference()
    with pytest.raises(ValueError, match='body-2.01-20250923'):
        build_body_reference.reference(programs.ap, programs.cp, public)


def test_body_reference_refuses_a_region_across_the_table_edge(build_fixtures):
    """Moving only part of a region would mix the two builds' addresses."""
    public = public_reference()
    table = next(row for row in public['programs']['appFw.so']['regions'] if row['offset'] == 0x4c7cf7c)
    table.update(offset=0x4c7cf78, bytes=16)
    with pytest.raises(ValueError, match='0x4c7cf78'):
        build_body_reference.reference(build_fixtures.body.ap, build_fixtures.body.cp, public)


# Committed build tables ----------------------------------------------------------------------

def test_builds_carry_the_findings_fingerprints():
    assert [build.key for build in BUILDS] == ['public-2.01', 'body-2.01-20250923']
    for build in BUILDS:
        assert (build.ap_sha256, build.cp_sha256) == FINDINGS[build.key]
        assert (build.ap_bytes, build.cp_bytes) == SIZES


def test_identification_reads_programs_only():
    """Custom slots and calibration differ between bodies of one build; identify never sees them."""
    assert list(inspect.signature(identify).parameters) == ['ap', 'cp']


def test_body_regions_differ_from_public_only_at_the_three_facts():
    public, body = regions(PUBLIC), regions(BODY)
    assert public['cpapp-b.bin'] == body['cpapp-b.bin']
    assert (len(public['appFw.so']), len(public['cpapp-b.bin'])) == (24, 39)
    moved = {0x4c7cf7c: 0x4c7cf6c}
    assert [moved.get(at, at) for at, _ in public['appFw.so']] == [at for at, _ in body['appFw.so']]
    differing = set()
    for (at, old), (_, new) in zip(public['appFw.so'], body['appFw.so']):
        assert len(old) == len(new), hex(at)
        differing |= {at + i for i, (a, b) in enumerate(zip(old, new)) if a != b}
    # add x0,x0,#0xac3 against #0xab3, and add x0,x0,#0xf7c against #0xf6c; the table bytes are equal
    assert differing == {0x3060a2d, 0x3060a2e, 0x3528811}


@pytest.mark.parametrize('build, converter, boot_log, table', [
    (PUBLIC, '00f03d91', '000c2b91', 0x4c7cf7c),
    (BODY, '00b03d91', '00cc2a91', 0x4c7cf6c),
])
def test_build_facts_are_each_builds_stock_bytes(build, converter, boot_log, table):
    assert stock(build, 'appFw.so', 0x3528810, 4) == build.converter_add == bytes.fromhex(converter)
    assert stock(build, 'appFw.so', 0x3060a2c, 4) == build.boot_log_add == bytes.fromhex(boot_log)
    assert build.look_table == table
    assert stock(build, 'appFw.so', table, 12) == STOCK_TABLE


def test_body_reference_keeps_the_public_color_units():
    public, body = public_reference(), json.loads((ASSETS / BODY.regions_file).read_text(encoding='utf-8'))
    assert body['color_units'] == public['color_units']
    assert {key: body[key] for key in ('schema', 'model', 'version')} == \
        {'schema': 'a7c2-factory-regions/1', 'model': 'ILCE-7CM2', 'version': '2.01'}


def test_stock_reads_up_to_both_edges_of_a_region():
    assert stock(PUBLIC, 'appFw.so', 0x35287f0, 4) == bytes.fromhex('1f400071')
    assert stock(PUBLIC, 'appFw.so', 0x3528870, 4) == bytes.fromhex('c0035fd6')
    assert len(stock(PUBLIC, 'appFw.so', 0x35287f0, 132)) == 132


@pytest.mark.parametrize('build, program, offset, size', [
    (BODY, 'appFw.so', 0x4c7cf7c, 12),     # the public table address holds no body stock
    (PUBLIC, 'appFw.so', 0x4c7cf6c, 12),   # nor the body's address any public stock
    (PUBLIC, 'appFw.so', 0x3528870, 8),    # runs past the end of the converter region
    (PUBLIC, 'appFw.so', 0x35287ec, 8),    # starts before it
    (PUBLIC, 'cpapp-b.bin', 0x3528810, 4),  # an appFw.so address in the other program
    (PUBLIC, 'appFw.so', 0x3528810, 0),
    (PUBLIC, 'appFw.so', 0x3528810, -4),
    (PUBLIC, 'BODYDATA.DAT', 0x3528810, 4),
])
def test_stock_outside_one_region_is_refused(build, program, offset, size):
    with pytest.raises(ValueError):
        stock(build, program, offset, size)


@pytest.mark.parametrize('offset, public, body', [
    (0x4c7cf6c, 0x4c7cf6c, 0x4c7cf6c),
    (0x4c7cf7b, 0x4c7cf7b, 0x4c7cf7b),
    (0x4c7cf7c, 0x4c7cf7c, 0x4c7cf6c),
    (0x4c7cf87, 0x4c7cf87, 0x4c7cf77),
    (0x4c7cf88, 0x4c7cf88, 0x4c7cf78),  # the end bound moves too, so a slice of the table stays 12 bytes
    (0x4c7cf89, 0x4c7cf89, 0x4c7cf89),
    (0x3528810, 0x3528810, 0x3528810),
    (0x3060a2c, 0x3060a2c, 0x3060a2c),
    (0x59896f0, 0x59896f0, 0x59896f0),
    (0, 0, 0),
])
def test_translate_moves_only_the_look_table(offset, public, body):
    assert (translate(offset, PUBLIC), translate(offset, BODY)) == (public, body)


# Synthetic builds ----------------------------------------------------------------------------

SIZE = 64 * 1024


def write_regions(path, programs, spans):
    """A regions file in the shipped format holding `programs`' bytes at each (offset, size)."""
    data = {'schema': 'a7c2-factory-regions/1', 'model': 'ILCE-7CM2', 'version': '2.01', 'color_units': {},
            'programs': {name: {'bytes': len(programs[name]), 'regions': [
                {'offset': at, 'bytes': size, 'zlib_base64': buildprofile.encode(programs[name][at:at + size])}
                for at, size in spans[name]]} for name in PROGRAMS}}
    path.write_text(json.dumps(data), encoding='utf-8')


@pytest.fixture
def two_builds(tmp_path, monkeypatch):
    """Builds a and b shaped like public and body: b's data after 0x4000 sits 16 bytes earlier, so its
    12-byte table is at 0x7ff0 instead of 0x8000; one instruction in a shared region differs, and so
    does a build stamp outside every region of cpapp-b.bin. Two Vertical Display windows, which no
    regions file holds, sit before 0x4000 and so hold the same bytes in both."""
    rng = random.Random(201)
    a_ap, a_cp = rng.randbytes(SIZE), rng.randbytes(SIZE)
    b_ap = bytearray(a_ap[:0x4000] + a_ap[0x4010:] + rng.randbytes(16))
    b_ap[0x1004:0x1008] = bytes.fromhex('00b03d91')
    b_cp = bytearray(a_cp)
    b_cp[0x9000:0x9008] = b'20250923'
    vertical = [(0x2000, a_ap[0x2000:0x2004]), (0x2400, a_ap[0x2400:0x2440])]
    result = {}
    for key, ap, cp, table in (('a', a_ap, a_cp, 0x8000), ('b', bytes(b_ap), bytes(b_cp), 0x7ff0)):
        spans = {'appFw.so': [(0x1000, 16), (table, 12)], 'cpapp-b.bin': [(0x3000, 8), (SIZE - 16, 16)]}
        write_regions(tmp_path / (key + '.json'), dict(zip(PROGRAMS, (ap, cp))), spans)
        build = Build(key=key, label_zh=key, ap_sha256=sha(ap), cp_sha256=sha(cp), ap_bytes=SIZE, cp_bytes=SIZE,
                      look_table=table, converter_add=ap[0x1004:0x1008], boot_log_add=ap[0x1008:0x100c],
                      regions_file=key + '.json')
        result[key] = SimpleNamespace(build=build, ap=ap, cp=cp, spans=spans, path=tmp_path / (key + '.json'))
    monkeypatch.setattr(buildprofile, 'ASSETS', tmp_path)
    monkeypatch.setattr(buildprofile, 'BUILDS', (result['a'].build, result['b'].build))
    monkeypatch.setattr(buildprofile, 'vertical_display_windows', lambda: list(vertical))
    return SimpleNamespace(**result, vertical=vertical)


def installed(programs, fill=0xee, vertical=()):
    """The programs with every region overwritten, as a finished tool install leaves them, and every
    (offset, stock bytes) window in `vertical` too."""
    files = [bytearray(programs.ap), bytearray(programs.cp)]
    for data, name in zip(files, PROGRAMS):
        for at, size in programs.spans[name]:
            data[at:at + size] = bytes([fill]) * size
    for at, raw in vertical:
        files[0][at:at + len(raw)] = bytes([fill]) * len(raw)
    return files


@pytest.mark.parametrize('key', ['a', 'b'])
def test_each_synthetic_build_identifies_stock_or_installed(two_builds, key):
    programs = getattr(two_builds, key)
    assert identify(programs.ap, programs.cp) is programs.build
    ap, cp = installed(programs)
    assert sha(ap) != programs.build.ap_sha256 and sha(cp) != programs.build.cp_sha256
    assert identify(bytes(ap), bytes(cp)) is programs.build


@pytest.mark.parametrize('key', ['a', 'b'])
def test_vertical_display_windows_are_normalised_too(two_builds, key):
    """Factory Restore's regions leave Vertical Display out (the vertical tool puts it back), but a
    camera with it installed must still identify, or every later write, the undo included, refuses."""
    programs = getattr(two_builds, key)
    ap, cp = installed(programs, vertical=two_builds.vertical)
    assert identify(bytes(ap), bytes(cp)) is programs.build
    # Only the first window written, as an interrupted install leaves it.
    partial = bytearray(programs.ap)
    partial[0x2000:0x2004] = b'\xee' * 4
    assert identify(bytes(partial), programs.cp) is programs.build


def test_identity_regions_are_the_restore_regions_and_the_vertical_windows(two_builds):
    b = two_builds.b
    restore = regions(b.build)
    assert restore == {'appFw.so': [(0x1000, b.ap[0x1000:0x1010]), (0x7ff0, b.ap[0x7ff0:0x7ffc])],
                       'cpapp-b.bin': [(0x3000, b.cp[0x3000:0x3008]), (SIZE - 16, b.cp[-16:])]}
    assert buildprofile.identity_regions(b.build) == {
        'appFw.so': [(0x1000, b.ap[0x1000:0x1010]), (0x2000, b.ap[0x2000:0x2004]), (0x2400, b.ap[0x2400:0x2440]),
                     (0x7ff0, b.ap[0x7ff0:0x7ffc])],
        'cpapp-b.bin': restore['cpapp-b.bin']}


def test_a_vertical_window_the_regions_file_already_holds_is_taken_once(two_builds, monkeypatch):
    """A regenerated regions file may hold the vertical windows itself; the bytes must then agree."""
    a = two_builds.a
    monkeypatch.setattr(buildprofile, 'vertical_display_windows', lambda: [(0x1004, a.ap[0x1004:0x1008])])
    assert buildprofile.identity_regions(a.build) == regions(a.build)
    assert identify(a.ap, a.cp) is a.build


@pytest.mark.parametrize('window, message', [
    ((0x1004, b'\x00\x00\x00\x00'), 'disagrees'),   # inside a region, other bytes
    ((0x0ffe, b'\x00' * 4), 'overlaps'),              # across a region's start
    ((0x100e, b'\x00' * 4), 'overlaps'),              # across a region's end
    ((SIZE - 2, b'\x00' * 4), 'invalid'),             # past the end of the program
    ((-4, b'\x00' * 4), 'invalid'),
    ((0x2000, b''), 'invalid'),
], ids=['disagrees', 'start edge', 'end edge', 'past the end', 'negative', 'empty'])
def test_a_vertical_window_that_does_not_fit_is_refused(two_builds, monkeypatch, window, message):
    a = two_builds.a
    if message == 'disagrees':
        window = (window[0], bytes(x ^ 0xff for x in a.ap[0x1004:0x1008]))
    monkeypatch.setattr(buildprofile, 'vertical_display_windows', lambda: [window])
    with pytest.raises(ValueError, match=message):
        buildprofile.identity_regions(a.build)
    with pytest.raises(ValueError, match=message):
        identify(a.ap, a.cp)


def test_another_builds_table_outside_these_regions_is_refused(two_builds):
    """The 27 Oct shape: a's table bytes written at a's address, which b doesn't own."""
    ap = bytearray(two_builds.b.ap)
    ap[0x8000:0x800c] = two_builds.a.ap[0x8000:0x800c]
    assert bytes(ap) != two_builds.b.ap
    with pytest.raises(UnsupportedFirmware):
        identify(bytes(ap), two_builds.b.cp)


def test_refusal_names_the_observed_digests(two_builds):
    ap, cp = installed(two_builds.b)
    ap[0x100] ^= 1
    with pytest.raises(UnsupportedFirmware) as refused:
        identify(bytes(ap), bytes(cp))
    message = str(refused.value)
    assert sha(ap)[:16] in message and sha(cp)[:16] in message


@pytest.mark.parametrize('ap_extra, cp_extra', [(1, 0), (0, -1), (0, -16), (-SIZE, -SIZE)],
                         ids=['longer', 'shorter', 'short read ending where the last region starts', 'empty'])
def test_programs_of_another_size_are_refused(two_builds, ap_extra, cp_extra):
    """A short read must never be completed by normalisation into a build's stock file."""
    ap = two_builds.a.ap + bytes(ap_extra) if ap_extra >= 0 else two_builds.a.ap[:ap_extra]
    cp = two_builds.a.cp + bytes(cp_extra) if cp_extra >= 0 else two_builds.a.cp[:cp_extra]
    with pytest.raises(UnsupportedFirmware):
        identify(ap, cp)


def test_identify_leaves_its_inputs_unchanged(two_builds):
    ap, cp = installed(two_builds.b)
    before = (bytes(ap), bytes(cp))
    assert identify(ap, cp) is two_builds.b.build
    assert (bytes(ap), bytes(cp)) == before


def test_regions_are_each_builds_own_stock_in_file_order(two_builds):
    found = regions(two_builds.b.build)
    assert found == {'appFw.so': [(0x1000, two_builds.b.ap[0x1000:0x1010]), (0x7ff0, two_builds.b.ap[0x7ff0:0x7ffc])],
                     'cpapp-b.bin': [(0x3000, two_builds.b.cp[0x3000:0x3008]), (SIZE - 16, two_builds.b.cp[-16:])]}


@pytest.mark.parametrize('damage', [
    lambda data: data.update(schema='a7c2-factory-regions/2'),
    lambda data: data.update(model='ILCE-7M4'),
    lambda data: data.update(version='2.00'),
    lambda data: data['programs']['appFw.so'].update(bytes=SIZE + 1),
    lambda data: data['programs']['appFw.so']['regions'][1].update(offset=SIZE - 4),
    lambda data: data['programs']['appFw.so']['regions'][1].update(offset=0x1008),
    lambda data: data['programs']['appFw.so']['regions'].reverse(),
    lambda data: data['programs']['appFw.so']['regions'][0].update(offset=-1),
    lambda data: data['programs']['cpapp-b.bin']['regions'][0].update(bytes=9),
    lambda data: data['programs'].pop('cpapp-b.bin'),
    lambda data: data['programs']['appFw.so']['regions'][0].pop('offset'),
    lambda data: data['programs']['appFw.so']['regions'][0].update(zlib_base64='AAAA'),
    lambda data: data['programs']['appFw.so']['regions'][0].update(zlib_base64='not base64!'),
], ids=['schema', 'model', 'version', 'program size', 'past the end', 'overlap', 'out of order', 'negative',
        'length', 'missing program', 'missing offset', 'not zlib', 'not base64'])
def test_a_damaged_regions_file_is_refused(two_builds, damage):
    data = json.loads(two_builds.a.path.read_text(encoding='utf-8'))
    damage(data)
    two_builds.a.path.write_text(json.dumps(data), encoding='utf-8')
    with pytest.raises(ValueError, match='a.json'):
        regions(two_builds.a.build)
    with pytest.raises(ValueError, match='a.json'):
        identify(two_builds.a.ap, two_builds.a.cp)
