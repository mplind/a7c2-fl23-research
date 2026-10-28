"""What carries over unchanged to the body build, proven on both Sony 2.01 compiles. Offline only.

Vertical Display writes 19 appFw.so windows, all in .text or in .rodata before 0x4ba1744, which the
body build holds at the same offsets with the same bytes. Factory Restore's regions leave those windows
out, because the vertical tool puts them back itself, so identification normalises a wider set,
buildprofile.identity_regions: without it a camera with Vertical Display installed would no longer
identify, and the firmware gate would refuse every later write, the undo included.

The name tools' /usr/share/app files and the .bss RAM addresses the native helpers read are proven the
same in both builds too, and every native-photo stage write stays inside each build's regions.

Real-firmware tests read A7C2_BUILD_FIXTURES through conftest.py's build_fixtures and skip when it is
unset; the name-file comparison also skips, naming the build, until both builds' name files are there
(build_resources). The rest run everywhere on the committed regions files.
"""
import bisect
import io
from pathlib import Path
import sys
from types import SimpleNamespace

from capstone import CS_ARCH_ARM64, CS_MODE_ARM, Cs
from capstone.arm64 import ARM64_OP_IMM, ARM64_OP_MEM, ARM64_OP_REG
from elftools.elf.elffile import ELFFile
import numpy as np
import pytest

from looktool import buildprofile, device_layout, nameworker, photobasis, photoio, resources, six
from looktool.buildprofile import BUILDS, identify, regions, translate
from looktool.devicesession import modules
import build_factory_reference

modules()
import compat  # noqa: E402  (modules() puts src/camera_runtime on sys.path)

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'src/vertical'))
from verticaltool import portraitlayout  # noqa: E402

PUBLIC, BODY = BUILDS
PROGRAMS = ('appFw.so', 'cpapp-b.bin')
EACH_BUILD = pytest.mark.parametrize('name, build', [('public', PUBLIC), ('body', BODY)], ids=['public', 'body'])
VERTICAL_WINDOWS = 19   # 17 portrait image references and two gauge blocks
SHIFTED = 0x4ba1744     # where the body's .rodata starts to sit lower than the public build's
# RAM addresses in appFw.so's .bss that native helpers read and write: the look bindings
# (src/looks/native/look_bindings.c), the audio buffer (src/shutter_sound/native/sound_probe.c,
# buffer_probe.c) and the vertical-display value (src/vertical/native/vertical_ram.c).
BSS_ADDRESSES = (0x7e70598, 0x7eac508, 0x7e735b8, 0x7e732b8)
# The (adrp, use) .text offsets that reach each one, found by bss_references on both builds.
BSS_SITES = {
    0x7e70598: {(0x2775e20, 0x2775e24), (0x2775e2c, 0x2775e30)},
    0x7eac508: {(0x2799c04, 0x2799c08), (0x2799c10, 0x2799c14)},
    0x7e735b8: {(0x2779b1c, 0x2779b20), (0x2779b28, 0x2779b2c)},
    0x7e732b8: {(0x27796b4, 0x27796b8), (0x2817dbc, 0x2817dc0)},
}


def programs(fixture):
    return {'appFw.so': fixture.ap, 'cpapp-b.bin': fixture.cp}


def changed(before, after):
    """Every offset at which `after` differs from `before`, two programs of one size."""
    assert len(before) == len(after)
    return np.flatnonzero(np.frombuffer(before, np.uint8) != np.frombuffer(after, np.uint8)).tolist()


class Spans:
    """The bytes the (offset, bytes) rows of one program cover, adjacent rows joined."""

    def __init__(self, rows):
        self.spans = []
        for at, raw in sorted(rows):
            if self.spans and at <= self.spans[-1][1]:
                self.spans[-1][1] = max(self.spans[-1][1], at + len(raw))
            else:
                self.spans.append([at, at + len(raw)])
        self.starts = [start for start, _ in self.spans]

    def cover(self, at, size=1):
        index = bisect.bisect_right(self.starts, at) - 1
        return index >= 0 and at + size <= self.spans[index][1]


def changes(before, after):
    """{offset: new byte} for every byte `after` changes in `before`, two programs of one size."""
    at = changed(before, after)
    return dict(zip(at, np.frombuffer(after, np.uint8)[at].tolist()))


def table(slot):
    """A distinct, valid full-precision custom-look table for each slot."""
    return bytes([slot]) * six.TABLE_BYTES


def section(ap, name):
    """(file offset, address, size) of ELF section `name` in appFw.so `ap`."""
    found = ELFFile(io.BytesIO(ap)).get_section_by_name(name)
    return found['sh_offset'], found['sh_addr'], found['sh_size']


DISASSEMBLER = Cs(CS_ARCH_ARM64, CS_MODE_ARM)
DISASSEMBLER.detail = True


def page_uses(ap, at, page, limit=64):
    """(offset, address) of each add-immediate, load or store after the adrp at `at` whose base is the
    register that adrp set to `page`, until the register is written again or control leaves through b,
    br or ret, and at most `limit` instructions on."""
    register = next(DISASSEMBLER.disasm(ap[at:at + 4], at)).operands[0].reg
    result = []
    for insn in DISASSEMBLER.disasm(ap[at + 4:at + 4 + 4 * limit], at + 4):
        operands = insn.operands
        if (insn.mnemonic == 'add' and len(operands) == 3 and operands[1].type == ARM64_OP_REG
                and operands[1].reg == register and operands[2].type == ARM64_OP_IMM):
            result.append((insn.address, page + operands[2].imm))
        result.extend((insn.address, page + operand.mem.disp) for operand in operands
                      if operand.type == ARM64_OP_MEM and operand.mem.base == register and operand.mem.index == 0)
        if register in insn.regs_access()[1] or insn.mnemonic in ('b', 'br', 'ret'):
            break
    return result


def bss_references(ap, addresses):
    """{address: {(adrp offset, use offset), …}}: the .text sites of appFw.so `ap` whose adrp plus an
    add, load or store resolves to each address."""
    offset, start, size = section(ap, '.text')
    assert offset == start   # .text is loaded at its file offset, so an instruction's offset is its address
    words = np.frombuffer(ap, '<u4', size // 4, offset).astype(np.int64)
    pc = start + 4 * np.arange(len(words), dtype=np.int64)
    pages = ((words >> 5) & 0x7ffff) << 2 | (words >> 29) & 3
    pages -= (pages & 1 << 20) << 1                       # sign-extend the 21-bit page count
    pages = (pc & ~0xfff) + (pages << 12)
    adrp = (words & 0x9f000000) == 0x90000000
    result = {address: set() for address in addresses}
    for i in np.flatnonzero(adrp & np.isin(pages, [address & ~0xfff for address in addresses])):
        for use, address in page_uses(ap, int(pc[i]), int(pages[i])):
            if address in result:
                result[address].add((int(pc[i]), use))
    return result


def label_table(raw):
    """(index count, group, {resource ID: text}) of a name file, this project's appended titles removed."""
    parsed = resources.decode(resources.before_custom(raw))
    return parsed['count'], parsed['group'], {rid: entry['text'] for rid, entry in parsed['entries'].items()}


def written(ap, windows, count, cut=0):
    """`ap` with the new bytes of the first `count` vertical windows written, and the first `cut` bytes
    of the next: the native worker writes them in plan order, so this is where an interrupted install
    stops."""
    result = bytearray(ap)
    for row in windows[:count]:
        new = bytes.fromhex(row['after_hex'])
        result[row['offset']:row['offset'] + len(new)] = new
    if cut:
        row = windows[count]
        result[row['offset']:row['offset'] + cut] = bytes.fromhex(row['after_hex'])[:cut]
    return bytes(result)


# Real firmware -------------------------------------------------------------------------------

def test_identity_regions_hold_each_builds_own_stock_bytes(build_fixtures):
    for build, fixture in ((PUBLIC, build_fixtures.public), (BODY, build_fixtures.body)):
        files = programs(fixture)
        for program, rows in buildprofile.identity_regions(build).items():
            for at, raw in rows:
                assert files[program][at:at + len(raw)] == raw, (build.key, program, hex(at))


@EACH_BUILD
def test_vertical_display_installed_identifies_its_build(build_fixtures, name, build):
    stock = getattr(build_fixtures, name)
    target, windows = portraitlayout.references(stock.ap, True)
    assert len(windows) == VERTICAL_WINDOWS and target != stock.ap
    assert identify(target, stock.cp) is build


@EACH_BUILD
@pytest.mark.parametrize('count, cut', [(1, 0), (VERTICAL_WINDOWS - 1, 54)],
                         ids=['first of 19 windows', 'stopped half way through the last'])
def test_partly_installed_vertical_display_identifies_its_build(build_fixtures, name, build, count, cut):
    stock = getattr(build_fixtures, name)
    windows = portraitlayout.canonical_windows(stock.ap)
    partial = written(stock.ap, windows, count, cut)
    assert partial != stock.ap
    assert identify(partial, stock.cp) is build


@EACH_BUILD
def test_vertical_display_changes_lie_inside_the_identity_set(build_fixtures, name, build):
    """R16: every byte Vertical Display changes, installing on stock, removing a full install and
    removing an interrupted one, lies inside the build's identity set; each result identifies as the
    build and each removal is the build's stock again."""
    stock = getattr(build_fixtures, name)
    windows = portraitlayout.canonical_windows(stock.ap)
    full = portraitlayout.references(stock.ap, True)[0]
    partial = written(stock.ap, windows, 7, 2)
    states = {'install': (stock.ap, full),
              'remove': (full, portraitlayout.references(full, False)[0]),
              'remove interrupted': (partial, portraitlayout.references(partial, False)[0])}
    identity = Spans(buildprofile.identity_regions(build)['appFw.so'])
    for label, (before, after) in states.items():
        offsets = changed(before, after)
        assert offsets, label
        outside = [at for at in offsets if not identity.cover(at)]
        assert not outside, (label, hex(outside[0]))
        assert identify(after, stock.cp) is build, label
    assert states['remove'][1] == states['remove interrupted'][1] == stock.ap


@EACH_BUILD
def test_other_tools_plan_on_top_of_vertical_display(build_fixtures, name, build):
    """FL2/FL3 and custom looks identify the build from the programs before they plan, so they must
    still find it on a camera that has Vertical Display installed."""
    stock = getattr(build_fixtures, name)
    vertical = portraitlayout.references(stock.ap, True)[0]
    _, _, fl23, _, _ = compat.plan(vertical, stock.cp, transitions=False)
    looks = device_layout.replace(fl23['appFw.so'], fl23['cpapp-b.bin'], {3: bytes([3]) * six.TABLE_BYTES},
                                  hash_checks=False, transitions=False)[2]
    assert portraitlayout.active(looks['appFw.so'])
    assert identify(looks['appFw.so'], looks['cpapp-b.bin']) is build


def test_identity_set_covers_every_generated_region(build_fixtures):
    """identity_regions holds every span build_factory_reference.py collects today, at each build's own
    address, so a generator change that adds a tool region cannot leave it out of identification
    unnoticed. (The committed public regions file predates the vertical windows.)"""
    generated = build_factory_reference.program_spans(programs(build_fixtures.public))
    assert sum(len(spans) for spans in generated.values()) == 44 + 41
    for build in BUILDS:
        identity = {program: Spans(rows) for program, rows in buildprofile.identity_regions(build).items()}
        for program, spans in generated.items():
            for at, size in spans:
                moved = translate(at, build) if program == 'appFw.so' else at
                assert identity[program].cover(moved, size), (build.key, program, hex(at), size)


def test_vertical_plan_on_body_equals_public(build_fixtures):
    """portraitlayout and portraitgauge plan the same windows, at the same offsets with the same bytes,
    on both builds, and find the same canvas roots and landscape references they check."""
    public, body = build_fixtures.public.ap, build_fixtures.body.ap
    windows = portraitlayout.canonical_windows(public)
    assert portraitlayout.canonical_windows(body) == windows
    assert [(row['offset'], bytes.fromhex(row['before_hex'])) for row in windows] == portraitlayout.stock_windows()
    for row in windows:
        at, size = row['offset'], len(row['before_hex']) // 2
        assert at + size <= SHIFTED, hex(at)
        assert body[at:at + size] == public[at:at + size], hex(at)
    for portrait, landscape, delta, _ in portraitlayout.PAIRS:
        for root in (portrait, landscape):
            assert body[root:root + 24] == public[root:root + 24], hex(root)
        assert body[landscape + delta:landscape + delta + 4] == public[landscape + delta:landscape + delta + 4]
    on = {name: portraitlayout.references(ap, True) for name, ap in (('public', public), ('body', body))}
    assert on['body'][1] == on['public'][1]
    assert changes(body, on['body'][0]) == changes(public, on['public'][0])


def test_name_resources_are_identical_or_parse_identically(build_resources):
    """Each /usr/share/app name file the name tools rewrite is byte-equal in both builds, or else holds
    the same label table once this project's appended titles are removed."""
    uncaptured = [name for name, files in build_resources.items() if files is None]
    if uncaptured:
        pytest.skip('R4: no name files yet for %s, in neither <build>/resources/ nor <A7C2_BUILD_FIXTURES>-resources/'
                    '<build>/: camera_fingerprint.py saves the camera\'s, read-only, in Task 10 step 1, and '
                    'extract_resources.py the public update\'s' % ', '.join(uncaptured))
    public, body = build_resources['public-2.01'], build_resources['body-2.01-20250923']
    for filename in nameworker.filenames():
        assert public[filename] == body[filename] or label_table(public[filename]) == label_table(body[filename]), filename


def test_public_name_resources_are_sony_stock(build_resources):
    """The public update's name files, from extract_resources.py, are the 68 files the name tools take,
    with Sony's 2860 indices and none of this project's titles."""
    files = build_resources['public-2.01']
    if files is None:
        pytest.skip('R4: no public-2.01 name files: run dev/desktop/extract_resources.py on Sony\'s BODYDATA.DAT')
    assert list(files) == nameworker.filenames() and len(files) == 68
    for filename, raw in files.items():
        parsed = resources.decode(raw)
        assert (parsed['count'], parsed['group']) == (2860, 5), filename
        assert resources.before_custom(raw) == raw, filename


def test_native_bss_addresses_are_referenced_identically(build_fixtures):
    """.text and .bss lie at the same addresses in both builds, and the .text sites whose adrp plus add,
    load or store reach each RAM address the native helpers use are the same, hold the same
    instructions, and are there at all."""
    public, body = build_fixtures.public.ap, build_fixtures.body.ap
    for name in ('.text', '.bss'):
        assert section(body, name) == section(public, name), name
    _, start, size = section(public, '.bss')
    assert all(start <= address < start + size for address in BSS_ADDRESSES)
    found = {'public': bss_references(public, BSS_ADDRESSES), 'body': bss_references(body, BSS_ADDRESSES)}
    for address in BSS_ADDRESSES:
        assert found['public'][address], hex(address)
        assert found['body'][address] == found['public'][address], hex(address)
        for site in found['public'][address]:
            for at in site:
                assert body[at:at + 4] == public[at:at + 4], (hex(address), hex(at))
    assert found['public'] == BSS_SITES


@pytest.fixture(scope='module')
def photo_stages(build_fixtures):
    """Native-photo stages planned on each build's stock, worked out once for the module, by label: a
    custom look with a stage in each slot alone and in all six, then slot 6's stage removed from all six
    and slot 1's from slot 1 alone. Each keeps .changes against stock, .mask (the installed stage mask)
    and .identified (the build its programs identify as)."""
    result = {}
    for name, build in (('public', PUBLIC), ('body', BODY)):
        stock = programs(getattr(build_fixtures, name))
        first = device_layout.replace(stock['appFw.so'], stock['cpapp-b.bin'], {1: table(1)}, build=build,
                                      hash_checks=False, transitions=False)[2]
        bank = photoio.neutral_bank(first['cpapp-b.bin'])

        def install(slots):
            return device_layout.replace(stock['appFw.so'], stock['cpapp-b.bin'], {slot: table(slot) for slot in slots},
                                         native_photo={slot: photobasis.pack(bank, tone=[16 + slot, 0, 0])[1] for slot in slots},
                                         native_bank=bank, build=build, hash_checks=False, transitions=False)[2]

        def remove(state, slot):
            return device_layout.deactivate(state['appFw.so'], state['cpapp-b.bin'], slot, bytes(six.TABLE_BYTES),
                                            native_bank=bank, build=build, hash_checks=False, transitions=False)[2]

        def kept(state):
            return SimpleNamespace(changes={program: changes(stock[program], state[program]) for program in PROGRAMS},
                                   mask=photoio.inspect(state['cpapp-b.bin'])['mask'],
                                   identified=identify(state['appFw.so'], state['cpapp-b.bin']))
        states = {}
        for slot in range(1, 7):
            state = install([slot])
            states['slot %d' % slot] = kept(state)
            if slot == 1:
                states['slot 1 removed'] = kept(remove(state, 1))
        state = install(range(1, 7))
        states['all six'] = kept(state)
        states['slot 6 removed'] = kept(remove(state, 6))
        result[name] = states
    return result


@EACH_BUILD
def test_native_photo_stage_writes_lie_inside_the_builds_regions(photo_stages, name, build):
    """R22: every byte a native-photo stage install or removal changes lies inside the build's regions
    (so inside its identity set too), and the programs still identify as the build."""
    restore = {program: Spans(rows) for program, rows in regions(build).items()}
    states = photo_stages[name]
    assert {label: state.mask for label, state in states.items()} == {
        **{'slot %d' % slot: 1 << (slot - 1) for slot in range(1, 7)},
        'slot 1 removed': 0, 'all six': 63, 'slot 6 removed': 31}
    for label, state in states.items():
        assert state.changes['cpapp-b.bin'], label
        for program in PROGRAMS:
            outside = [at for at in state.changes[program] if not restore[program].cover(at)]
            assert not outside, (label, program, hex(outside[0]))
        assert state.identified is build, label


def test_native_photo_stages_write_the_same_cp_bytes_on_both_builds(photo_stages):
    for label, public in photo_stages['public'].items():
        assert photo_stages['body'][label].changes['cpapp-b.bin'] == public.changes['cpapp-b.bin'], label


# Committed tables ----------------------------------------------------------------------------

@EACH_BUILD
def test_custom_look_windows_lie_inside_the_restore_regions(name, build):
    """R23: every AP restore window of runtime_for(build), every cp_sources window of both kinds and the
    CP six-table span lie inside the build's regions, so a regenerated regions file that dropped one
    fails here, without fixtures."""
    restore = {program: Spans(rows) for program, rows in regions(build).items()}
    runtime = device_layout.runtime_for(build)
    assert sorted(spec['kind'] for spec in runtime['ap_sources']) == sorted(spec['kind'] for spec in runtime['cp_sources']) \
        == ['fl23', 'stock']
    for spec in runtime['ap_sources']:
        for window in spec['restore']:
            assert restore['appFw.so'].cover(window['offset'], len(window['hex']) // 2), (spec['kind'], hex(window['offset']))
    for spec in runtime['cp_sources']:
        for window in spec['windows']:
            assert restore['cpapp-b.bin'].cover(window['offset'], len(window['before']) // 2), (spec['kind'], hex(window['offset']))
    assert restore['cpapp-b.bin'].cover(six.TABLE_FILE, 32 + 6 * six.TABLE_BYTES)


@EACH_BUILD
def test_identity_regions_are_the_restore_regions_and_the_vertical_windows(name, build):
    """Factory Restore's write set stays the regions file; identification adds the 19 vertical windows,
    none of which the regions file holds."""
    restore, identity = regions(build), buildprofile.identity_regions(build)
    assert (len(restore['appFw.so']), len(restore['cpapp-b.bin'])) == (24, 39)
    assert identity['cpapp-b.bin'] == restore['cpapp-b.bin']
    vertical = portraitlayout.stock_windows()
    assert len(vertical) == VERTICAL_WINDOWS
    assert identity['appFw.so'] == sorted(restore['appFw.so'] + vertical)
