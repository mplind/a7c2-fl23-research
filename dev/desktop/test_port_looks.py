"""Custom looks installed against the identified build, on both Sony 2.01 compiles. Offline only.

Real-firmware tests read A7C2_BUILD_FIXTURES through conftest.py's build_fixtures and skip when it is
unset. The rest run everywhere on the committed runtime-v1.json and regions files.
"""
import bisect
from concurrent.futures import ThreadPoolExecutor
import dataclasses
import importlib.util
import inspect
import json
from types import SimpleNamespace

import numpy as np
import pytest
from unicorn import UC_ARCH_ARM64, UC_HOOK_CODE, UC_MODE_ARM, Uc
from unicorn.arm64_const import UC_ARM64_REG_LR, UC_ARM64_REG_PC, UC_ARM64_REG_X0, UC_ARM64_REG_X1, UC_ARM64_REG_X2

from looktool import device_layout, firmware, six, standalone
from looktool.buildprofile import BUILDS, LOOK_TABLE_BYTES, PUBLIC_LOOK_TABLE, identify, regions, stock, translate
from looktool.devicesession import modules

core = modules()[1]
import compat  # noqa: E402  (modules() puts src/camera_runtime on sys.path)

PUBLIC, BODY = BUILDS
PROGRAMS = ('appFw.so', 'cpapp-b.bin')
CONVERTER, CONVERTER_END = 0x35287f0, 0x3528874
TABLE_ADD = 0x3528828        # `add x0,x0,#table` in every converter template (template offset 0x38)
PUBLIC_ADD = bytes.fromhex('00f03d91')
TITLE_BRANCH = 0x1b5cd7c
LABEL_IDS = list(range(0x0200ab2c, 0x0200ab32))
# The native look each binding 0..11 selects through the custom-look converter's table.
LOOKS = bytes([0, 3, 2, 1, 0x10, 0xf, 0x11, 0x12, 5, 0xd, 0x13, 0x14])
EACH_BUILD = pytest.mark.parametrize('name, build', [('public', PUBLIC), ('body', BODY)], ids=['public', 'body'])
# The body build's digests, computed from the A7C2_BUILD_FIXTURES programs (see
# test_body_runtime_digests_are_those_of_the_fixtures).
BODY_DIGESTS = {
    'stock_sha256': '77fa856ed5812124ffec507857ec48af43159357b2c8a341cb15f3d5c1076d54',
    'fl23_sha256': '06d1f717c316135d2b52ea80a2fe74e136aa44d43745bd4fade9cad720faf03f',
    'cp_code_sha256': 'e3e9ef5709edd85abd9fbeb142188a190d5fb594751d78a23a5f780c56478e2f',
}
# Public-build results of the custom-look planner at c67f81b, before the port (full-file SHA-256 of
# appFw.so and cpapp-b.bin, and of each transition manifest as sorted JSON). The port must not move
# a single public byte.
PUBLIC_BEFORE_THE_PORT = {
    'install-1': ('da024a269f129317efbf0b4f9970fc7f607bcfab58b7416e1c7393cc2c730df3',
                  '05e1596bab79c1be41b1750e9efadbfa8a7f2efa87714a58e148fc07ea106bc1'),
    'install-1-forward': 'a8dc955ef18140fc09e16a63f75f056cd7070d47dc398761e229fb42acb27c33',
    'install-1-reverse': '83bad8e70541bcb1936fc835a0d61a1328aae75f9db1912a35a73edeabdf89ac',
    'install-63': ('12059503aa178fb325f32f57fd25e2e9805ef49aef6cb0ad6bb2afe953a8bd10',
                   '0e3fb82c7b21b97ab28efed29b3d2107ccb07ed090120e4bd488c1e94c84bbea'),
    'install-37': ('f7300342ec4d81c0a5be2644baa9449b4713a77c46bd7fadafdff6751331a580',
                   '8ef4abba15b9edd15c71048dc04b9e3edff1b8eb9e578c582da1669ff17742a3'),
    'deactivate-37-3': ('cb30d130098cc50e6b7b1bab9772401d2b3686c1bfbd1919872af8e01857c3d5',
                        '6a090af1b55069b65c3dff19b14d2342e41f4fbc2130177788fa1a36267eece9'),
    'deactivate-37-3-forward': 'dcd3b6559fb027274b317f3646310e60e437b48aa8e3a8c5324b802926dcab9d',
    'deactivate-37-3-reverse': '588ca0871baf283d0c53ebfe35a0fd3ff86315add54b587ccdb60f41de518b6c',
    'deactivate-to-0': ('63ce9062901ca8da83aefe807f0ab4ade3703ce14e627971d63e1f97a4c11309',
                        '45c53a7a32190582ed985b4f6aa9fd878f014296d06d2710a6d3967ece4bf623'),
    'fl23-then-18': ('7c32d5d45ca76c374294ea5bdf726751ee55c429a1ab48980bfca25713339b90',
                     '7d374d0ac11e4180483f6bcf2cfe398c2c15f33aba7c5ae9fb0f19ec55b71fa5'),
}
LAYOUT_FUNCTIONS = ('identify_ap', 'structural_ap', 'identify', 'structural', 'replace', 'deactivate',
                    'before_first_table')


def table(slot):
    """A distinct, valid full-precision table for each custom slot."""
    return bytes([slot]) * six.TABLE_BYTES


def slots(mask):
    return [slot for slot in range(1, 7) if mask >> (slot - 1) & 1]


def programs(fixture):
    return {'appFw.so': fixture.ap, 'cpapp-b.bin': fixture.cp}


def install(source, mask, build, **options):
    """device_layout.replace of the slots in `mask`, each with its own table, on `source`."""
    return device_layout.replace(source['appFw.so'], source['cpapp-b.bin'], {slot: table(slot) for slot in slots(mask)},
                                 build=build, **options)


def digests(result):
    return firmware.sha(result['appFw.so']), firmware.sha(result['cpapp-b.bin'])


CHUNK = 1 << 20


def change(before, after):
    """Every byte `after` changes in `before`, per program: {program: {offset: new byte}}. Whole 1 MiB
    chunks that are equal are skipped; the others are compared byte by byte."""
    result = {}
    for program in PROGRAMS:
        old, new = before[program], after[program]
        assert len(old) == len(new), program
        changed = {}
        for start in range(0, len(old), CHUNK):
            a, b = old[start:start + CHUNK], new[start:start + CHUNK]
            if a != b:
                left, right = np.frombuffer(a, np.uint8), np.frombuffer(b, np.uint8)
                at = np.flatnonzero(left != right)
                changed.update(zip((at + start).tolist(), right[at].tolist()))
        result[program] = changed
    return result


def applied(before, changes):
    """The programs `changes` (from change()) was taken from."""
    result = {}
    for program in PROGRAMS:
        data = bytearray(before[program])
        for at, value in changes[program].items():
            data[at] = value
        result[program] = bytes(data)
    return result


@pytest.fixture(scope='module')
def sweep(build_fixtures):
    """Every custom-look state on each build's stock, worked out once for the module: for each slot
    mask 1..63 the install of those slots (installs[mask]), and the deactivation of that install's
    highest slot (deactivations[mask], so deactivations[1] is mask 0). Each is kept as change()."""
    result = {}
    for name, build in (('public', PUBLIC), ('body', BODY)):
        base = programs(getattr(build_fixtures, name))
        installs, deactivations = {}, {}
        for mask in range(1, 64):
            after = install(base, mask, build, hash_checks=False, transitions=False)[2]
            installs[mask] = change(base, after)
            off = device_layout.deactivate(after['appFw.so'], after['cpapp-b.bin'], max(slots(mask)), bytes(six.TABLE_BYTES),
                                           hash_checks=False, transitions=False, build=build)[2]
            deactivations[mask] = change(base, off)
        result[name] = SimpleNamespace(stock=base, installs=installs, deactivations=deactivations)
    return result


def state(states, mask):
    """The sweep's programs with slots `mask` installed; mask 0 is the last slot deactivated."""
    return applied(states.stock, states.installs[mask] if mask else states.deactivations[1])


# The converter in a unicorn CPU -------------------------------------------------------------

OUTPUT, CALLER = 0x30000000, 0x31000000
STOCK_PATH = CONVERTER_END   # where the converter hands a binding it has no look for back to stock code
TABLE_PAGE = BODY.look_table & ~0xfff   # holds both builds' look tables
assert PUBLIC_LOOK_TABLE & ~0xfff == TABLE_PAGE


class Converter:
    """`ap`'s converter page and look-table page in a unicorn CPU, as the camera maps them."""

    def __init__(self, ap):
        self.cpu = Uc(UC_ARCH_ARM64, UC_MODE_ARM)
        for page in (CONVERTER & ~0xfff, TABLE_PAGE):
            self.cpu.mem_map(page, 0x1000)
            self.cpu.mem_write(page, ap[page:page + 0x1000])
        self.cpu.mem_map(OUTPUT, 0x1000)
        self.cpu.mem_map(CALLER, 0x1000)
        self.cpu.hook_add(UC_HOOK_CODE, self._stop_on_stock_path)
        self.stock_path = False

    def _stop_on_stock_path(self, uc, address, size, _):
        if address == STOCK_PATH:
            self.stock_path = True
            uc.emu_stop()

    def look(self, selector, binding):
        """The look byte stored for (w0=selector, w1=binding), or None when it takes the stock path."""
        self.stock_path = False
        self.cpu.mem_write(OUTPUT, b'\xa5')
        # Garbage above the w registers must not matter.
        for register, value in ((UC_ARM64_REG_X0, 0xdead_beef_0000_0000 | selector),
                                (UC_ARM64_REG_X1, 0x5a5a_5a5a_0000_0000 | binding),
                                (UC_ARM64_REG_X2, OUTPUT), (UC_ARM64_REG_LR, CALLER)):
            self.cpu.reg_write(register, value)
        self.cpu.emu_start(CONVERTER, CALLER, count=100)
        if self.stock_path:
            assert bytes(self.cpu.mem_read(OUTPUT, 1)) == b'\xa5'
            return None
        assert self.cpu.reg_read(UC_ARM64_REG_PC) == CALLER  # returned, not cut off by the count
        return bytes(self.cpu.mem_read(OUTPUT, 1))[0]


def expected_look(mask, selector, binding):
    """What the custom-look converter must store: 0xff for selector 16; custom slot 249..254 for
    selector 10..15 with binding 0 when that slot is installed; else the native look of bindings
    0..11, and the stock path (None) for any other binding."""
    if selector == 16:
        return 0xff
    if binding == 0 and 10 <= selector <= 15 and mask >> (selector - 10) & 1:
        return 249 + selector - 10
    return LOOKS[binding] if binding < len(LOOKS) else None


SELECTORS = (*range(20), 0xffff, 0xffffffff)
BINDINGS = (*range(13), 255, 0xffffffff)


# Real firmware -------------------------------------------------------------------------------

def test_body_look_install_differs_from_public_only_at_build_facts(sweep):
    """For every mask, install and deactivate change the same bytes on both builds, except that the
    map lands in the body's look table and the template's table add is the body's own."""
    moved = 0
    for kind in ('installs', 'deactivations'):
        for mask, public in getattr(sweep['public'], kind).items():
            body = getattr(sweep['body'], kind)[mask]
            expected = {translate(at, BODY): value for at, value in public['appFw.so'].items()}
            expected.update(zip(range(TABLE_ADD, TABLE_ADD + 4), BODY.converter_add))
            assert body['appFw.so'] == expected, (kind, mask)
            assert body['cpapp-b.bin'] == public['cpapp-b.bin'], (kind, mask)
            assert any(BODY.look_table <= at < BODY.look_table + LOOK_TABLE_BYTES for at in body['appFw.so'])
            assert not any(PUBLIC_LOOK_TABLE <= at < PUBLIC_LOOK_TABLE + LOOK_TABLE_BYTES for at in body['appFw.so'])
            moved += 1
    assert moved == 2 * 63


@EACH_BUILD
def test_look_changes_lie_inside_the_builds_regions(sweep, name, build):
    """Every byte an install or a deactivation changes, for every mask, lies inside one of the build's
    tool regions, so the programs still identify as that build mid-job and afterwards."""
    states = sweep[name]
    tool = {program: [(at, at + len(raw)) for at, raw in rows] for program, rows in regions(build).items()}
    starts = {program: [start for start, _ in spans] for program, spans in tool.items()}

    def inside(program, at):
        index = bisect.bisect_right(starts[program], at) - 1
        return index >= 0 and at < tool[program][index][1]
    every = [(kind, mask, changes) for kind in ('installs', 'deactivations') for mask, changes in getattr(states, kind).items()]
    assert len(every) == 2 * 63
    for kind, mask, changes in every:
        for program in PROGRAMS:
            assert changes[program], (kind, mask, program)
            outside = sorted(at for at in changes[program] if not inside(program, at))
            assert not outside, (kind, mask, program, hex(outside[0]))

    def identified(changes):
        result = applied(states.stock, changes)
        return identify(result['appFw.so'], result['cpapp-b.bin'])
    # buildprofile.identify hashes both whole programs. hashlib releases the GIL while it hashes, so
    # four threads check the 126 states in about half the time.
    with ThreadPoolExecutor(4) as pool:
        builds = list(pool.map(identified, [changes for _, _, changes in every]))
    assert [(kind, mask) for (kind, mask, _), found in zip(every, builds) if found is not build] == []


@EACH_BUILD
def test_deactivating_a_slot_equals_installing_the_others(sweep, name, build):
    """deactivate rebuilds appFw.so from the build's own stock windows, so the result is exactly the
    install of the remaining slots."""
    states = sweep[name]
    for mask in range(2, 64):
        remaining = mask & ~(1 << (max(slots(mask)) - 1))
        if remaining:
            assert states.deactivations[mask]['appFw.so'] == states.installs[remaining]['appFw.so'], mask


def test_body_lut_converter_maps_through_the_moved_table(sweep):
    """A unicorn run of the installed converter, for every mask, reads the map at 0x4c7cf6c."""
    body = sweep['body']
    for mask in range(64):
        ap = state(body, mask)['appFw.so']
        assert ap[BODY.look_table:BODY.look_table + LOOK_TABLE_BYTES] == LOOKS, mask
        # The public table address holds other body .rodata: reading it would give other looks.
        assert ap[PUBLIC_LOOK_TABLE:PUBLIC_LOOK_TABLE + LOOK_TABLE_BYTES] != LOOKS
        converter = Converter(ap)
        actual = {(selector, binding): converter.look(selector, binding) for selector in SELECTORS for binding in BINDINGS}
        assert actual == {key: expected_look(mask, *key) for key in actual}, mask


def test_the_public_table_add_would_read_the_wrong_body_bytes(sweep):
    """Control for the converter test: the public template on the body build maps other looks."""
    ap = bytearray(state(sweep['body'], 63)['appFw.so'])
    ap[TABLE_ADD:TABLE_ADD + 4] = PUBLIC_ADD
    converter = Converter(bytes(ap))
    assert [converter.look(0, binding) for binding in range(12)] != list(LOOKS)


def test_body_identify_ap_recognises_installed_masks(sweep):
    body = sweep['body']
    for mask in range(64):
        ap = state(body, mask)['appFw.so']
        expected = {'kind': 'stock-lut', 'mask': mask, 'label_ids': LABEL_IDS}
        assert device_layout.structural_ap(ap, build=BODY) == expected, mask
        assert device_layout.structural_ap(ap) == expected, mask
        with pytest.raises(ValueError, match='converter bytes conflict'):
            device_layout.structural_ap(ap, build=PUBLIC)
    # Whole-file digests: every single slot, none, all, and two mixed masks.
    for mask in (0, 1, 2, 4, 8, 16, 32, 37, 42, 63):
        ap = state(body, mask)['appFw.so']
        expected = {'kind': 'stock-lut', 'mask': mask, 'label_ids': LABEL_IDS}
        assert device_layout.identify_ap(ap, build=BODY) == expected, mask
        if mask in (0, 37, 63):
            assert device_layout.identify_ap(ap) == expected, mask
            with pytest.raises(ValueError, match='Unsupported AP identity'):
                device_layout.identify_ap(ap, build=PUBLIC)


def test_body_stock_and_fl23_are_first_installs(build_fixtures):
    body = programs(build_fixtures.body)
    _, _, fl23, _, _ = compat.plan(body['appFw.so'], body['cpapp-b.bin'], transitions=False)
    for source, kind in ((body, 'stock'), (fl23, 'fl23')):
        expected = {'kind': kind, 'mask': 0, 'label_ids': LABEL_IDS, 'first_install': True}
        assert device_layout.identify_ap(source['appFw.so'], build=BODY) == expected
        assert device_layout.structural_ap(source['appFw.so'], build=BODY) == expected
        identity = device_layout.identify(source['appFw.so'], source['cpapp-b.bin'])
        assert (identity['kind'], identity['mask'], identity['first_install']) == (kind, 0, True)
        with pytest.raises(ValueError, match='Unsupported AP identity'):
            device_layout.identify_ap(source['appFw.so'], build=PUBLIC)
    # The public stock converter is not the body's: no first install on the wrong build.
    with pytest.raises(ValueError, match='converter bytes conflict'):
        device_layout.structural_ap(body['appFw.so'], build=PUBLIC)


def test_body_deactivate_restores_body_stock(build_fixtures):
    """Install three looks on body stock and take them off again, with whole-file identity checks and
    both transitions at every step. The install's reverse gives body stock byte for byte; taking every
    slot off leaves body stock with only the dormant converter and CP runtime on top."""
    body = programs(build_fixtures.body)
    raw = {slot: device_layout.before_first_table(body['appFw.so'], body['cpapp-b.bin'], slot, build=BODY) for slot in (1, 3, 6)}
    # replace and deactivate identify the build from the programs themselves.
    forward, reverse, installed = install(body, 0b100101, None)
    assert device_layout.identify(installed['appFw.so'], installed['cpapp-b.bin'], build=BODY)['mask'] == 0b100101
    restored = firmware.apply(installed, reverse)
    assert digests(restored) == (BODY.ap_sha256, BODY.cp_sha256)
    assert firmware.apply(body, forward) == installed
    current = installed
    for slot, mask in ((3, 0b100001), (1, 0b100000), (6, 0)):
        forward, reverse, after = device_layout.deactivate(current['appFw.so'], current['cpapp-b.bin'], slot, raw[slot])
        assert device_layout.identify(after['appFw.so'], after['cpapp-b.bin'], build=BODY)['mask'] == mask
        assert firmware.apply(after, reverse) == current
        assert firmware.apply(current, forward) == after
        current = after
    # Mask 0 leaves the dormant converter, its title branch and the map at the body's table, and the
    # dormant CP runtime. Every other byte, the slot labels and the public table address included, is
    # body stock.
    expected = bytearray(body['appFw.so'])
    expected[CONVERTER:CONVERTER_END] = device_layout.template_for(BODY, 0)
    expected[TITLE_BRANCH:TITLE_BRANCH + 4] = bytes.fromhex(device_layout.runtime()['title_branch'])
    expected[BODY.look_table:BODY.look_table + LOOK_TABLE_BYTES] = LOOKS
    assert current['appFw.so'] == bytes(expected)
    dormant = bytearray(body['cpapp-b.bin'])
    for window in next(spec for spec in device_layout.runtime()['cp_sources'] if spec['kind'] == 'stock')['windows']:
        dormant[window['offset']:window['offset'] + len(window['after']) // 2] = bytes.fromhex(window['after'])
    assert current['cpapp-b.bin'] == bytes(dormant)


@EACH_BUILD
def test_fl23_and_custom_looks_install_in_either_order(build_fixtures, name, build):
    """FL2/FL3 planned on a camera with custom looks keeps them, and FL2/FL3 then looks ends in the
    same programs as looks then FL2/FL3 (src/looks/tests/test_install_order.py, on both builds)."""
    base = programs(getattr(build_fixtures, name))
    looks = {2: table(2), 5: table(5)}
    _, _, fl23, _, _ = compat.plan(base['appFw.so'], base['cpapp-b.bin'], transitions=False)
    _, _, first = device_layout.replace(fl23['appFw.so'], fl23['cpapp-b.bin'], looks, transitions=False)
    _, _, lut = device_layout.replace(base['appFw.so'], base['cpapp-b.bin'], looks, transitions=False)
    identity, enabled, second, forward, reverse = compat.plan(lut['appFw.so'], lut['cpapp-b.bin'])
    assert (identity['kind'], identity['mask'], enabled) == ('lut', 0b10010, False)
    assert second == first
    # The installed looks are kept: converter, tables and slot labels.
    assert second['appFw.so'][CONVERTER:CONVERTER_END] == device_layout.template_for(build, 0b10010)
    assert [six.read_tables(second['cpapp-b.bin'])[slot - 1] for slot in looks] == list(looks.values())
    for at in (0x59896f0 + (slot - 1) * 0xb8 for slot in looks):
        assert second['appFw.so'][at:at + 4] == lut['appFw.so'][at:at + 4] != base['appFw.so'][at:at + 4]
    identity = device_layout.identify(second['appFw.so'], second['cpapp-b.bin'])
    assert (identity['kind'], identity['mask']) == ('fl23-lut', 0b10010)
    assert compat.plan(first['appFw.so'], first['cpapp-b.bin'], transitions=False)[1]
    assert firmware.apply(second, reverse) == lut
    assert firmware.apply(lut, forward) == second
    assert identify(second['appFw.so'], second['cpapp-b.bin']) is build


def test_body_runtime_digests_are_those_of_the_fixtures(build_fixtures):
    """The body's builds entry holds the digests of its own stock, of FL2/FL3 planned on it, and of its
    custom-look CP code. The same computations on the public fixtures give the public digests."""
    asset = device_layout.runtime()
    for name, build in (('public', PUBLIC), ('body', BODY)):
        base = programs(getattr(build_fixtures, name))
        _, _, fl23, _, _ = compat.plan(base['appFw.so'], base['cpapp-b.bin'], transitions=False)
        _, _, installed = install(base, 1, build, hash_checks=False, transitions=False)
        computed = {'stock_sha256': firmware.sha(base['appFw.so']), 'fl23_sha256': firmware.sha(fl23['appFw.so']),
                    'cp_code_sha256': device_layout.code_hash(installed['cpapp-b.bin'])}
        if build is BODY:
            assert computed == asset['builds'][BODY.key] == BODY_DIGESTS
        else:
            sources = {spec['kind']: spec['sha256'] for spec in asset['ap_sources']}
            assert computed == {'stock_sha256': sources['stock'], 'fl23_sha256': sources['fl23'],
                                'cp_code_sha256': asset['cp_code_sha256']}


def test_body_restore_windows_hold_body_stock_and_body_fl23(build_fixtures):
    """runtime_for(BODY)'s restore windows: 'stock' holds body stock and 'fl23' holds what compat.plan
    writes on body stock, each at the body's own addresses."""
    body = programs(build_fixtures.body)
    _, _, fl23, _, _ = compat.plan(body['appFw.so'], body['cpapp-b.bin'], transitions=False)
    sources = {spec['kind']: spec for spec in device_layout.runtime_for(BODY)['ap_sources']}
    for kind, source in (('stock', body), ('fl23', fl23)):
        for window in sources[kind]['restore']:
            raw = bytes.fromhex(window['hex'])
            assert source['appFw.so'][window['offset']:window['offset'] + len(raw)] == raw, (kind, hex(window['offset']))


def test_public_custom_looks_are_unchanged_by_the_port(build_fixtures):
    public = programs(build_fixtures.public)
    results = {}
    forward, reverse, one = install(public, 1, None)
    results.update({'install-1': digests(one), 'install-1-forward': manifest_digest(forward),
                    'install-1-reverse': manifest_digest(reverse)})
    results['install-63'] = digests(install(public, 63, PUBLIC, hash_checks=False, transitions=False)[2])
    m37 = install(public, 37, PUBLIC, hash_checks=False, transitions=False)[2]
    results['install-37'] = digests(m37)
    forward, reverse, off = device_layout.deactivate(m37['appFw.so'], m37['cpapp-b.bin'], 3, bytes(six.TABLE_BYTES))
    results.update({'deactivate-37-3': digests(off), 'deactivate-37-3-forward': manifest_digest(forward),
                    'deactivate-37-3-reverse': manifest_digest(reverse)})
    for slot in (1, 6):
        off = device_layout.deactivate(off['appFw.so'], off['cpapp-b.bin'], slot, bytes(six.TABLE_BYTES),
                                       hash_checks=False, transitions=False, build=PUBLIC)[2]
    results['deactivate-to-0'] = digests(off)
    _, _, fl23, _, _ = compat.plan(public['appFw.so'], public['cpapp-b.bin'], transitions=False)
    results['fl23-then-18'] = digests(install(fl23, 18, PUBLIC, hash_checks=False, transitions=False)[2])
    assert results == PUBLIC_BEFORE_THE_PORT


def manifest_digest(manifest):
    return firmware.sha(json.dumps(manifest, sort_keys=True).encode())


# Committed tables ----------------------------------------------------------------------------

@pytest.mark.parametrize('build', BUILDS, ids=[build.key for build in BUILDS])
def test_template_for_reencodes_only_the_table_add(build):
    templates = device_layout.runtime()['ap_templates']
    assert len(templates) == 64
    at = TABLE_ADD - CONVERTER
    assert at == 0x38
    for mask, public in enumerate(map(bytes.fromhex, templates)):
        assert public[at:at + 4] == PUBLIC_ADD, mask
        assert device_layout.template_for(build, mask) == public[:at] + build.converter_add + public[at + 4:], mask
    assert device_layout.runtime_for(build)['ap_templates'] == [device_layout.template_for(build, m).hex() for m in range(64)]


@pytest.mark.parametrize('build', BUILDS, ids=[build.key for build in BUILDS])
def test_the_template_slot_is_add_x0_x0_of_the_builds_table(build):
    """template_for swaps only the add: the adrp before it names the same page in both builds."""
    word = int.from_bytes(build.converter_add, 'little')
    # ADD (immediate, 64-bit, no shift): 1001000100 imm12 Rn Rd
    assert (word >> 22, (word >> 10) & 0xfff, (word >> 5) & 31, word & 31) == (0b1001000100, build.look_table & 0xfff, 0, 0)
    assert build.look_table & ~0xfff == PUBLIC_LOOK_TABLE & ~0xfff


@pytest.mark.parametrize('mask', [-1, 64, 1.0, '1', True, None])
def test_template_for_refuses_a_mask_outside_six_slots(mask):
    with pytest.raises(ValueError, match='six-slot'):
        device_layout.template_for(BODY, mask)


def test_template_for_refuses_a_template_without_the_public_table_add(monkeypatch):
    asset = device_layout.runtime()
    changed = bytearray.fromhex(asset['ap_templates'][5])
    changed[0x39] ^= 0x40
    asset['ap_templates'][5] = changed.hex()
    monkeypatch.setattr(device_layout, 'runtime', lambda: asset)
    assert device_layout.template_for(BODY, 4)
    with pytest.raises(ValueError, match='0x3528828'):
        device_layout.template_for(BODY, 5)
    with pytest.raises(ValueError, match='0x3528828'):
        device_layout.template_for(PUBLIC, 5)


@pytest.mark.skipif(not importlib.util.find_spec('keystone'), reason='Optional research assembler required')
@pytest.mark.parametrize('build', BUILDS, ids=[build.key for build in BUILDS])
def test_every_template_matches_its_assembler_source_on_each_build(build):
    for mask in range(64):
        code, branch, mapping = standalone.assemble(mask, build)
        assert code == device_layout.template_for(build, mask), mask
        assert branch.hex() == device_layout.runtime()['title_branch']
        assert mapping == LOOKS
    assert standalone.assemble(37) == standalone.assemble(37, PUBLIC)


def test_public_runtime_is_the_bundled_runtime():
    """runtime-v1.json is written for the public build, and its stock restore windows are public stock."""
    asset = device_layout.runtime()
    assert device_layout.runtime_for(PUBLIC) == asset
    stock_source = next(spec for spec in asset['ap_sources'] if spec['kind'] == 'stock')
    assert stock_source['sha256'] == PUBLIC.ap_sha256
    for window in stock_source['restore']:
        raw = bytes.fromhex(window['hex'])
        assert stock(PUBLIC, 'appFw.so', window['offset'], len(raw)) == raw, hex(window['offset'])


def test_body_runtime_moves_only_the_build_facts():
    asset, body = device_layout.runtime(), device_layout.runtime_for(BODY)
    assert {key: value for key, value in body.items() if key not in ('ap_templates', 'ap_sources', 'cp_code_sha256')} == \
        {key: value for key, value in asset.items() if key not in ('ap_templates', 'ap_sources', 'cp_code_sha256')}
    assert body['cp_code_sha256'] == BODY_DIGESTS['cp_code_sha256']
    assert [spec['kind'] for spec in body['ap_sources']] == [spec['kind'] for spec in asset['ap_sources']] == ['stock', 'fl23']
    for public, moved in zip(asset['ap_sources'], body['ap_sources']):
        assert moved['sha256'] == BODY_DIGESTS[public['kind'] + '_sha256']
        assert moved['bytes'] == public['bytes'] == BODY.ap_bytes
        assert [window['offset'] for window in moved['restore']] == [translate(window['offset'], BODY) for window in public['restore']]
        assert BODY.look_table in [window['offset'] for window in moved['restore']]
        for before, after in zip(public['restore'], moved['restore']):
            old, new = bytes.fromhex(before['hex']), bytes.fromhex(after['hex'])
            differing = {before['offset'] + i for i, (a, b) in enumerate(zip(old, new)) if a != b}
            # Only the stock converter's table add differs; FL2/FL3's converter is the same in both.
            assert differing == ({0x3528811} if public['kind'] == 'stock' and before['offset'] == CONVERTER else set())
            if public['kind'] == 'stock':
                assert new == stock(BODY, 'appFw.so', after['offset'], len(new))


def test_runtime_pins_the_body_digests():
    builds = device_layout.runtime()['builds']
    assert builds == {BODY.key: BODY_DIGESTS}
    assert builds[BODY.key]['stock_sha256'] == BODY.ap_sha256


def test_a_build_without_custom_look_runtime_is_refused():
    other = dataclasses.replace(BODY, key='other-2.01', ap_sha256='0' * 64)
    with pytest.raises(ValueError, match='other-2.01'):
        device_layout.runtime_for(other)
    with pytest.raises(ValueError, match='other-2.01'):
        device_layout.structural_ap(b'stand-in appFw.so', build=other)


def test_a_builds_entry_for_another_stock_is_refused(monkeypatch):
    asset = device_layout.runtime()
    asset['builds'][BODY.key]['stock_sha256'] = PUBLIC.ap_sha256
    monkeypatch.setattr(device_layout, 'runtime', lambda: asset)
    with pytest.raises(ValueError, match=BODY.key):
        device_layout.runtime_for(BODY)


@pytest.mark.parametrize('function', LAYOUT_FUNCTIONS)
def test_layout_functions_take_the_build_as_an_optional_keyword(function):
    parameter = inspect.signature(getattr(device_layout, function)).parameters['build']
    assert parameter.kind is inspect.Parameter.KEYWORD_ONLY and parameter.default is None


@pytest.mark.parametrize('function', ['identify', 'structural', 'replace', 'deactivate', 'before_first_table'])
def test_unidentified_programs_are_refused_before_any_layout_work(function):
    from looktool.buildprofile import UnsupportedFirmware
    arguments = {'identify': (), 'structural': (), 'replace': ({1: table(1)},), 'deactivate': (1, table(1)),
                 'before_first_table': (1,)}[function]
    with pytest.raises(UnsupportedFirmware):
        getattr(device_layout, function)(b'stand-in appFw.so', b'stand-in cpapp-b.bin', *arguments)
