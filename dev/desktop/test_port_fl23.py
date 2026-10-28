"""FL2/FL3 planned against the identified build, on both Sony 2.01 compiles. Offline only.

Real-firmware tests read A7C2_BUILD_FIXTURES through conftest.py's build_fixtures and skip when it is
unset. The rest run everywhere on the committed patches.json and regions files.
"""
from collections import namedtuple
import inspect
import json
import re
import struct

import pytest
from unicorn import UC_ARCH_ARM64, UC_HOOK_CODE, UC_MODE_ARM, Uc
from unicorn.arm64_const import UC_ARM64_REG_LR, UC_ARM64_REG_X0, UC_ARM64_REG_X1, UC_ARM64_REG_X2

from looktool import direct, firmware
from looktool.buildprofile import BUILDS, UnsupportedFirmware, identify, regions, stock, translate
from looktool.devicesession import modules

core = modules()[1]
import compat  # noqa: E402  (modules() puts src/camera_runtime on sys.path)

PUBLIC, BODY = BUILDS
CONVERTER = 0x3528804
# The look each Creative Look index 0..11 selects after FL2/FL3: the stock ten, then FL2 and FL3.
LOOKS = [0, 3, 2, 1, 0x10, 0xf, 0x11, 0x12, 5, 0xd, 0x13, 0x14]
EACH_BUILD = pytest.mark.parametrize('name, build', [('public', PUBLIC), ('body', BODY)], ids=['public', 'body'])
Prop = namedtuple('Prop', 'data attr')


def sites():
    """(program, public offset, before, after) of every write in patches.json."""
    manifest = json.loads((core.BASE / 'assets/patches.json').read_text(encoding='utf-8'))
    return [(program, int(w['file_offset'], 16), bytes.fromhex(w['before_hex']), bytes.fromhex(w['after_hex']))
            for program, spec in zip(core.PROGRAMS, manifest) for w in spec['writes']]


def at_in(build, program, offset):
    """Where a public-build patch offset lies in `build`: only appFw.so addresses can move."""
    return translate(offset, build) if program == 'appFw.so' else offset


def programs(fixture):
    return {'appFw.so': fixture.ap, 'cpapp-b.bin': fixture.cp}


@pytest.fixture(scope='module')
def plans(build_fixtures):
    """compat.plan of each stock fixture, with both transitions, worked out once for the module."""
    return {name: compat.plan(getattr(build_fixtures, name).ap, getattr(build_fixtures, name).cp)
            for name in ('public', 'body')}


# Real firmware -------------------------------------------------------------------------------

def test_the_stored_identity_keeps_its_format(plans):
    """R18 corrects the reminder's text only. validate() compares the identity a workspace stored with
    the one plan() returns, so its keys and values, provenance_checked included, stay as they were."""
    for name in ('public', 'body'):
        assert plans[name][0] == {'kind': 'version-2.01', 'mask': None, 'provenance_checked': False,
                                  'firmware_version': '2.01', 'version_source': 'user-camera-version-screen'}


def test_body_plan_writes_the_same_bytes_as_public(build_fixtures, plans):
    public, body = plans['public'][2], plans['body'][2]
    expected = {name: bytearray(data) for name, data in programs(build_fixtures.body).items()}
    for program, at, _, after in sites():
        moved = at_in(BODY, program, at)
        assert body[program][moved:moved + len(after)] == public[program][at:at + len(after)] == after, (program, hex(at))
        expected[program][moved:moved + len(after)] = after
    # ...and nothing else: the body result is body stock with exactly those bytes written.
    assert body == {name: bytes(data) for name, data in expected.items()}


def test_body_plan_checks_against_body_stock(build_fixtures, plans):
    identity, enabled, _, forward, reverse = plans['body']
    assert (identity['kind'], enabled) == ('version-2.01', False)
    assert forward and reverse
    # The 27 Oct camera holds public stock at the converter inside the body build: never write to it.
    hybrid = build_fixtures.hybrid
    with pytest.raises(UnsupportedFirmware):
        compat.plan(hybrid.ap, hybrid.cp)
    with pytest.raises(ValueError, match='補丁位置衝突：appFw.so 0x3528804'):
        compat.plan(hybrid.ap, hybrid.cp, build=BODY, transitions=False)


@pytest.mark.parametrize('name, other', [('body', PUBLIC), ('public', BODY)])
def test_each_build_is_checked_against_its_own_stock_only(build_fixtures, name, other):
    fixture = getattr(build_fixtures, name)
    with pytest.raises(ValueError, match='補丁位置衝突：appFw.so 0x3528804'):
        compat.plan(fixture.ap, fixture.cp, build=other, transitions=False)


def test_body_converter_maps_all_twelve_looks(plans):
    ap = plans['body'][2]['appFw.so']
    cpu = Uc(UC_ARCH_ARM64, UC_MODE_ARM)
    page = CONVERTER & ~0xfff
    cpu.mem_map(page, 0x1000)
    cpu.mem_write(page, ap[page:page + 0x1000])
    output, caller = 0x30000000, 0x31000000
    cpu.mem_map(output, 0x1000)
    cpu.mem_map(caller, 0x1000)
    refused = []

    def stop_on_refusal(uc, address, size, _):
        if address == CONVERTER + 112:  # the stock path after the converter: no look for this index
            refused.append(address)
            uc.emu_stop()
    cpu.hook_add(UC_HOOK_CODE, stop_on_refusal)

    def run(w1):
        refused.clear()
        cpu.mem_write(output, b'\xa5')
        # Garbage above w1 and in x0 must not matter: the converter reads w1 and loads its own table.
        for register, value in ((UC_ARM64_REG_X0, 0xdeadbeefcafef00d), (UC_ARM64_REG_X1, 0x5a5a5a5a00000000 | w1),
                                (UC_ARM64_REG_X2, output), (UC_ARM64_REG_LR, caller)):
            cpu.reg_write(register, value)
        cpu.emu_start(CONVERTER, caller, count=100)
        return bytes(cpu.mem_read(output, 1))[0], bool(refused)

    assert [run(index) for index in range(12)] == [(look, False) for look in LOOKS]
    for index in (12, 13, 255, 0xffffffff):
        assert run(index) == (0xa5, True), index


def test_body_reverse_returns_body_stock(build_fixtures, plans):
    _, _, after, forward, reverse = plans['body']
    restored = firmware.apply(after, reverse)
    assert core.sha(restored['appFw.so']).startswith('77fa856e')
    assert (core.sha(restored['appFw.so']), core.sha(restored['cpapp-b.bin'])) == (BODY.ap_sha256, BODY.cp_sha256)
    assert restored == programs(build_fixtures.body)
    assert firmware.apply(restored, forward) == after


@EACH_BUILD
def test_fl23_changes_lie_inside_the_builds_regions(build_fixtures, plans, name, build):
    """Re-identification after the write (or after an interrupted one) must still find the build."""
    before, after, forward = programs(getattr(build_fixtures, name)), plans[name][2], plans[name][3]
    tool = regions(build)
    for program in core.PROGRAMS:
        # Every changed byte: put the regions back and nothing else may differ.
        outside = bytearray(after[program])
        for at, raw in tool[program]:
            outside[at:at + len(raw)] = before[program][at:at + len(raw)]
        assert outside == before[program], program
        # Every window the writer rewrites lies inside one region.
        windows = forward['files'][program]['windows']
        assert windows, program
        for window in windows:
            at, size = int(window['offset'], 16), window['bytes']
            assert any(start <= at and at + size <= start + len(raw) for start, raw in tool[program]), (program, hex(at))
    assert identify(after['appFw.so'], after['cpapp-b.bin']) is build


def test_body_plan_recognises_its_own_result(plans):
    after = plans['body'][2]
    identity, enabled, again, forward, reverse = compat.plan(after['appFw.so'], after['cpapp-b.bin'])
    assert (identity['kind'], enabled, again, forward, reverse) == ('version-2.01', True, after, None, None)


def test_body_plan_completes_an_interrupted_install(build_fixtures, plans):
    partial = {name: bytearray(data) for name, data in programs(build_fixtures.body).items()}
    for program, at, _, after in sites()[::2]:
        moved = at_in(BODY, program, at)
        partial[program][moved:moved + len(after)] = after
    partial = {name: bytes(data) for name, data in partial.items()}
    _, enabled, after, _, reverse = compat.plan(partial['appFw.so'], partial['cpapp-b.bin'])
    assert not enabled
    assert after == plans['body'][2]
    assert firmware.apply(after, reverse) == partial


def test_desktop_fl23_enable_installs_the_body_plan(build_fixtures, plans):
    """direct.plan is what the app's FL2/FL3 action runs: on the body build it must plan the same."""
    units = {0x02a40001: Prop(bytes(8192), 0), 0x02a4000d: Prop(bytes(28672), 0)}
    target, wanted, _ = direct.plan(programs(build_fixtures.body), [{}, units], 'fl23_enable')
    assert target == plans['body'][2]
    assert set(wanted[1]) == set(units)


# Committed tables ----------------------------------------------------------------------------

def test_public_stock_is_the_patch_manifest_before_bytes():
    """patches.json stays public-only; its before bytes are the public build's own stock."""
    for program, at, before, after in sites():
        assert len(before) == len(after), (program, hex(at))
        assert stock(PUBLIC, program, at, len(before)) == before, (program, hex(at))


def test_body_stock_differs_from_public_only_at_the_converter_add():
    differing = set()
    for program, at, before, _ in sites():
        body = stock(BODY, program, at_in(BODY, program, at), len(before))
        differing |= {(program, at + i) for i, (a, b) in enumerate(zip(before, body)) if a != b}
    assert differing == {('appFw.so', 0x3528811)}
    assert stock(BODY, 'appFw.so', 0x3528810, 4) == BODY.converter_add


def test_plan_takes_the_build_as_an_optional_keyword():
    parameters = inspect.signature(compat.plan).parameters
    assert list(parameters) == ['ap', 'cp', 'version', 'transitions', 'build']
    assert parameters['build'].kind is inspect.Parameter.KEYWORD_ONLY and parameters['build'].default is None


def test_unidentified_programs_are_refused_before_any_planning():
    with pytest.raises(UnsupportedFirmware):
        compat.plan(b'stand-in appFw.so', b'stand-in cpapp-b.bin')


def test_the_install_reminder_says_the_firmware_build_was_checked():
    """R18: plan() identifies the build by full-file fingerprint, so the reminder shown before an install
    no longer says the firmware goes unchecked, in Chinese or in English."""
    from desktopapp.en_engine import ENGINE
    english = ENGINE[compat.WARNING]
    assert '不驗證' not in compat.WARNING and '指紋' in compat.WARNING
    assert "isn't verified" not in english and 'fingerprint' in english
    # R56: identify() puts every tool-owned region back to stock before hashing, so another tool's change
    # inside those regions passes it; only changes outside them are refused before anything is written.
    assert '其他工具改過的程式會在寫入前被拒絕' not in compat.WARNING and '以外' in compat.WARNING
    assert 'Programs changed by other tools are refused' not in english and 'outside the regions' in english


def test_an_appfw_write_in_the_look_table_follows_the_build(monkeypatch):
    """No FL2/FL3 write lies in the moved look table today; one that did would land at the build's
    own table and be checked against that build's stock there."""
    table, body_table = 0x4c7cf7c, BODY.look_table
    written = bytes(range(0x40, 0x4c))
    patches = [{'writes': [{'file_offset': hex(table), 'before_hex': stock(PUBLIC, 'appFw.so', table, 12).hex(),
                            'after_hex': written.hex()}]}, {'writes': []}]
    read_json = core.read_json
    monkeypatch.setattr(core, 'read_json', lambda path: patches if path.name == 'patches.json' else read_json(path))
    ap = bytearray(table + 0x1000)
    ap[body_table:body_table + 12] = stock(BODY, 'appFw.so', body_table, 12)
    _, enabled, after, _, _ = compat.plan(bytes(ap), bytes(16), build=BODY, transitions=False)
    assert not enabled
    expected = bytearray(ap)
    expected[body_table:body_table + 12] = written
    assert after['appFw.so'] == bytes(expected)
    ap[body_table] ^= 1  # not the body's stock any more
    with pytest.raises(ValueError, match='補丁位置衝突：appFw.so 0x4c7cf6c'):
        compat.plan(bytes(ap), bytes(16), build=BODY, transitions=False)


def test_runtime_spans_are_the_ones_runtime_so_reads():
    source = (core.BASE / 'native/runtime.c').read_text(encoding='utf-8')
    offsets = re.search(r'offsets\[6\]=\{([^}]*)\}', source).group(1).split(',')
    lengths = re.search(r'lengths\[6\]=\{([^}]*)\}', source).group(1).split(',')
    assert core.RUNTIME_SPANS == tuple((int(at, 16), int(n)) for at, n in zip(offsets, lengths))
    raw = bytearray(1832)
    struct.pack_into('<8sIIqqqQII', raw, 0, b'A7RUN001', 1, 6, 0, 0, 0, 0, 16, 0)
    parsed = core.parse_native('runtime', bytes(raw))
    assert tuple((span['offset'], span['length']) for span in parsed['spans']) == core.RUNTIME_SPANS


def test_runtime_spans_cover_every_appfw_write():
    """The post-reload check reads these spans; together they hold every appFw.so FL2/FL3 write."""
    for program, at, before, _ in sites():
        if program == 'appFw.so':
            assert any(start <= at and at + len(before) <= start + n for start, n in core.RUNTIME_SPANS), hex(at)


@pytest.mark.parametrize('build', BUILDS, ids=[build.key for build in BUILDS])
def test_runtime_spans_are_the_same_on_both_builds(build):
    assert core.runtime_spans(build) == core.RUNTIME_SPANS


def test_a_build_that_moves_a_runtime_span_is_refused(monkeypatch):
    """runtime.so reads its compiled offsets on every camera, so it can't follow a moved span."""
    monkeypatch.setattr(core, 'RUNTIME_SPANS', core.RUNTIME_SPANS + ((0x4c7cf70, 16),))
    assert core.runtime_spans(PUBLIC) == core.RUNTIME_SPANS
    with pytest.raises(ValueError, match='body-2.01-20250923'):
        core.runtime_spans(BODY)
    with pytest.raises(ValueError, match='body-2.01-20250923'):
        compat.plan(b'stand-in appFw.so', b'stand-in cpapp-b.bin', build=BODY)
