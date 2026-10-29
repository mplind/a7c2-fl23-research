"""What carries over unchanged to the body build, proven on both Sony 2.01 compiles. Offline only.

Vertical Display writes 19 appFw.so windows, all in .text or in .rodata before 0x4ba1744, which the
body build holds at the same offsets with the same bytes. Factory Restore's regions leave those windows
out, because the vertical tool puts them back itself, so identification normalises a wider set,
buildprofile.identity_regions: without it a camera with Vertical Display installed would no longer
identify, and the firmware gate would refuse every later write, the undo included.

The name tools' /usr/share/app files and the .bss RAM addresses the native helpers read are proven the
same in both builds too, and every native-photo stage write stays inside each build's regions.

Around every place a tool writes either program, 256 bytes either side hold the same bytes in both
builds (R30), except the three build facts and instructions that are each build's own adrp + add/ldr
pair to the same data object, which the body's shorter .rodata holds lower.

Real-firmware tests read A7C2_BUILD_FIXTURES through conftest.py's build_fixtures and skip when it is
unset; the name-file comparison also skips, naming the build, until both builds' name files are there
(build_resources). The rest run everywhere on the committed regions files.
"""
import bisect
import io
from pathlib import Path
import struct
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

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'src/vertical'))
from verticaltool import portraitgauge, portraitlayout  # noqa: E402

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
CONTEXT = 256           # bytes either side of a write site that must match (R30)
TARGET_BYTES = 16       # an accepted pair's two targets must hold at least this many equal bytes
CHANGED = 128           # bytes that differ within the shifted .rodata, all in one ID table (derive_shifts)
# (start, end, shift) spans of public .rodata addresses and how many bytes lower the body holds each,
# as derive_shifts finds them in the fixtures; None for public bytes the body has no counterpart of.
# Public inserts a 4-byte ID at 0x4ba1744 and 4 bytes of padding at 0x4ba179c, then more padding
# that ends at 0x4c102e8; the 16-byte shift holds to the end of public .rodata.
SHIFTS = [(0, 0x4ba1744, 0), (0x4ba1744, 0x4ba1748, None), (0x4ba1748, 0x4ba179c, 4), (0x4ba179c, 0x4ba17a0, None),
          (0x4ba17a0, 0x4c102e8, 8), (0x4c102e8, 0x51a09e4, 16)]
# The build facts at tool sites: the bytes of Build.boot_log_add and Build.converter_add that differ.
BUILD_FACTS = {0x3060a2d: 'start-up sound log add (Build.boot_log_add)',
               0x3060a2e: 'start-up sound log add (Build.boot_log_add)',
               0x3528811: 'converter look-table add (Build.converter_add)'}
# Each instruction that differs within a write site's context, other than the facts: its use offset,
# then (adrp offset, public target, body target). All are .text adds of log and assert strings in the
# .rodata the body holds 16 lower; none is written by a tool.
RESOLVED_PAIRS = {
    0x3060a70: (0x3060a68, 0x4c14aec, 0x4c14adc),   # 'Failure adf_sys_get_syst…', after the sound block
    0x3060a7c: (0x3060a74, 0x4c14fb8, 0x4c14fa8),   # 'void model::sequence_boo…'
    0x3060a80: (0x3060a6c, 0x4c149fa, 0x4c149ea),   # 'sequence/sequence_boot.c'
    0x35286f4: (0x35286ec, 0x4c83648, 0x4c83638),   # 'void infra_wrapper_imagi…', around the converter
    0x3528798: (0x3528790, 0x4c7db9c, 0x4c7db8c),   # 'infra_wrapper_imaging_ip…'
    0x35287b4: (0x35287ac, 0x4c83648, 0x4c83638),
    0x3528890: (0x3528884, 0x4c7db9c, 0x4c7db8c),
    0x35288a8: (0x35288a0, 0x4c83280, 0x4c83270),
    0x3528938: (0x352892c, 0x4c7db9c, 0x4c7db8c),
    0x3528950: (0x3528948, 0x4c82ab8, 0x4c82aa8),
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
    """(offset, address, mnemonic) of each add-immediate, load or store after the adrp at `at` whose base is the
    register that adrp set to `page`, until the register is written again or control leaves through b,
    br or ret, and at most `limit` instructions on."""
    register = next(DISASSEMBLER.disasm(ap[at:at + 4], at)).operands[0].reg
    result = []
    for insn in DISASSEMBLER.disasm(ap[at + 4:at + 4 + 4 * limit], at + 4):
        operands = insn.operands
        if (insn.mnemonic == 'add' and len(operands) == 3 and operands[1].type == ARM64_OP_REG
                and operands[1].reg == register and operands[2].type == ARM64_OP_IMM):
            result.append((insn.address, page + operands[2].imm, insn.mnemonic))
        result.extend((insn.address, page + operand.mem.disp, insn.mnemonic) for operand in operands
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
        for use, address, _ in page_uses(ap, int(pc[i]), int(pages[i])):
            if address in result:
                result[address].add((int(pc[i]), use))
    return result


def instruction(ap, at):
    """The capstone instruction at offset `at` of appFw.so `ap`, or None when the word does not decode."""
    return next(DISASSEMBLER.disasm(ap[at:at + 4], at), None)


def pairs_with(ap, at, text):
    """(adrp offset, use offset, address) of each adrp + add/ldr pair the instruction at `at` belongs to,
    as the adrp or as the add/ldr, looking back at most 64 instructions within .text span `text`."""
    def kind(mnemonic):
        return mnemonic == 'add' or mnemonic.startswith('ldr')
    found = instruction(ap, at)
    if found is None:
        return []
    if found.mnemonic == 'adrp':
        return [(at, use, address) for use, address, mnemonic in page_uses(ap, at, found.operands[1].imm) if kind(mnemonic)]
    for adrp in range(at - 4, max(text[0], at - 4 * 64) - 1, -4):
        candidate_adrp = instruction(ap, adrp)
        if candidate_adrp is None or candidate_adrp.mnemonic != 'adrp':
            continue
        uses = [(adrp, use, address) for use, address, mnemonic in page_uses(ap, adrp, candidate_adrp.operands[1].imm)
                if use == at and kind(mnemonic)]
        if uses:
            return uses
    return []


def shift_at(spans, address):
    """How many bytes lower the body holds public address `address`, from (start, end, shift) spans;
    None outside them."""
    return next((shift for start, end, shift in spans if start <= address < end), None)


def derive_shifts(public, body):
    """SHIFTS as the fixtures show it. .rodata starts at the same address in both builds and is 16 bytes
    shorter in the body, and every step is public bytes the body lacks:
    - the 16-byte shift holds from where it starts (found from the end of .rodata backwards) to the
      end of .rodata;
    - before it, the first differing .rodata byte starts an insertion, as long as it takes (in 4-byte
      steps) for the bytes after it to line up with the body's again, and that shift holds as far as
      the two keep lining up, where the next insertion is measured the same way;
    - this goes on until a shift explains the bytes all the way to the 16-byte one, apart from at most
      CHANGED bytes (one ID table whose entries differ, at public 0x4bf9b12). That shift ends where
      the zero padding before the 16-byte shift stops reading the same at it.
    Every shifted span is checked to differ, so shifted, in at most CHANGED bytes."""
    p_offset, p_address, p_size = section(public, '.rodata')
    b_offset, b_address, b_size = section(body, '.rodata')
    assert p_offset == p_address == b_offset == b_address and p_size - b_size == 16
    end, body_end = p_offset + p_size, b_offset + b_size
    p, b = np.frombuffer(public, np.uint8), np.frombuffer(body, np.uint8)
    first = p_offset + int(np.flatnonzero(p[p_offset:body_end] != b[p_offset:body_end])[0])
    start16 = first + int(np.flatnonzero(b[first:body_end] != p[first + 16:end])[-1]) + 1   # in the body
    spans, at, shift = [(0, first, 0)], first, 0
    while True:
        size = next(size for size in range(4, 17, 4)
                    if public[at + size:at + size + 64] == body[at - shift:at - shift + 64])
        spans.append((at, at + size, None))
        at, shift = at + size, shift + size
        if int((p[at:start16 + shift] != b[at - shift:start16]).sum()) <= CHANGED:
            stop = start16 + int(np.flatnonzero(b[start16:body_end] != p[start16 + shift:body_end + shift])[0]) + shift
            spans += [(at, stop, shift), (stop, end, 16)]
            break
        stop = at + int(np.flatnonzero(p[at:at + body_end - (at - shift)] != b[at - shift:body_end])[0])
        spans.append((at, stop, shift))
        at = stop
    for start, stop, shift in spans:
        if shift:
            assert int((p[start:stop] != b[start - shift:stop - shift]).sum()) <= CHANGED, (hex(start), shift)
    return spans


def tool_spans(public):
    """(program, public offset, size) of every span a tool writes in either program: the spans
    build_factory_reference.py collects from the public programs, joined with the public identity
    set, which also holds the regions of older tool releases."""
    spans = build_factory_reference.program_spans(programs(public))
    for program, rows in buildprofile.identity_regions(PUBLIC).items():
        spans[program] = build_factory_reference.merged(spans[program] + [(at, len(raw)) for at, raw in rows])
    return [(program, at, size) for program in PROGRAMS for at, size in spans[program]]


# The imm12 field of an add/ldr (bits 10-21): the only bits a shifted target may change in an instruction.
IMMEDIATE = 0xfff << 10


def context_check(public, body, sites, *, text, shifts, moved, facts):
    """R30 over the CONTEXT bytes either side of each (program, offset, size) site, public and
    body being {program: bytes} and `moved` the body offset of a public appFw.so offset. Returns
    (pairs, failures): pairs maps the use offset of each accepted pair to (adrp offset, public target,
    body target); failures lists (program, public offset, reason) for every other differing byte. The
    `facts` offsets of appFw.so are exempt. A differing instruction is accepted only when it lies
    outside every written span, is part of the same adrp + add/ldr pair in both builds, differs only in
    its immediate (IMMEDIATE: same opcode and registers), the body's target is the public one less
    shift_at(shifts, it), and both targets hold the same TARGET_BYTES, not all one value."""
    differing = {}
    for program, at, size in sites:
        there = moved(at) if program == 'appFw.so' else at
        a = public[program][at - CONTEXT:at + size + CONTEXT]
        b = body[program][there - CONTEXT:there + size + CONTEXT]
        assert len(a) == len(b) == size + 2 * CONTEXT, (program, hex(at))
        for i in changed(a, b):
            differing[(program, at - CONTEXT + i)] = there - CONTEXT + i
    written = [(program, at, at + size) for program, at, size in sites]
    pairs, failures, instructions = {}, [], {}
    for (program, offset), there in sorted(differing.items()):
        if program == 'appFw.so' and offset in facts:
            continue
        if program != 'appFw.so' or offset != there or not text[0] <= offset < text[1]:
            failures.append((program, offset, 'differs outside .text'))
        else:
            instructions.setdefault(offset & ~3, []).append(offset)
    ap, bp = public['appFw.so'], body['appFw.so']
    for at, offsets in sorted(instructions.items()):
        found = pairs_with(ap, at, text)
        if any(program == 'appFw.so' and start < at + 4 and at < end for program, start, end in written):
            reason = 'inside a tool-written span'
        elif not found or [row[:2] for row in found] != [row[:2] for row in pairs_with(bp, at, text)]:
            reason = 'not the same adrp + add/ldr pair in both builds'
        elif (struct.unpack_from('<I', ap, at)[0] ^ struct.unpack_from('<I', bp, at)[0]) & ~IMMEDIATE:
            reason = 'the instructions differ outside the immediate'
        else:
            reason = None
            for (adrp, use, target), (_, _, body_target) in zip(found, pairs_with(bp, at, text)):
                shift = shift_at(shifts, target)
                data = ap[target:target + TARGET_BYTES]
                if shift is None or body_target != target - shift:
                    reason = 'targets %#x and %#x are not one address shifted' % (target, body_target)
                elif data != bp[body_target:body_target + TARGET_BYTES] or len(set(data)) < 2:
                    reason = 'targets %#x and %#x hold different data' % (target, body_target)
                else:
                    pairs[use] = (adrp, target, body_target)
        if reason:
            failures += [('appFw.so', offset, reason) for offset in offsets]
    return pairs, failures


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
                    '<build>/: copy them there from a checked camera_fingerprint.py capture (Task 10 step 1), '
                    'and run extract_resources.py for the public update\'s' % ', '.join(uncaptured))
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


@pytest.fixture(scope='module')
def shifts(build_fixtures):
    return derive_shifts(build_fixtures.public.ap, build_fixtures.body.ap)


def test_rodata_shift_boundaries_come_from_the_fixtures(build_fixtures, shifts):
    """The shift spans R30 uses are what the fixtures show: the extra 4-byte ID 0x00020000 at 0x4ba1744,
    4 bytes of padding after its list at 0x4ba179c (the two move the rest 8), the padding that ends at
    0x4c102e8, and the end of public .rodata. From there on the body's addresses are the public ones:
    its first load segment is 16 bytes shorter and the second starts at the same address, so
    .data.rel.ro (verticalpersist's descriptor at 0x57bbb90 included) is not shifted."""
    public, body = build_fixtures.public.ap, build_fixtures.body.ap
    # derive_shifts lines the spans up itself; what follows checks what it doesn't name.
    assert shifts == SHIFTS
    assert public[0x4ba1744:0x4ba1748] == (0x00020000).to_bytes(4, 'little')
    assert public[0x4ba179c:0x4ba17a0] == bytes(4)
    p, b = np.frombuffer(public, np.uint8), np.frombuffer(body, np.uint8)
    table = 0x4ba17a0 + np.flatnonzero(p[0x4ba17a0:0x4c102e8] != b[0x4ba1798:0x4c102e0])
    assert len(table) == CHANGED and 0x4bf9b12 <= table[0] and table[-1] < 0x4bf9d8d   # the one changed ID table
    loads = [[(segment['p_offset'], segment['p_vaddr'], segment['p_filesz']) for segment in ELFFile(io.BytesIO(ap)).iter_segments()
              if segment['p_type'] == 'PT_LOAD'] for ap in (public, body)]
    assert loads[0][0][2] - loads[1][0][2] == 16 and loads[0][1:] == loads[1][1:]
    offset, _, size = section(public, '.data.rel.ro')   # 0x57bbb90 is a file offset, as verticalpersist reads it
    assert offset <= 0x57bbb90 < offset + size and public[0x57bbb90:0x57bbbb0] == body[0x57bbb90:0x57bbbb0]


def test_every_write_site_has_identical_context_in_both_builds(build_fixtures, shifts):
    """R30: 256 bytes either side of every tool write site, and the site, hold the same bytes in both
    builds, at the site's own address in each, except the three build facts and the adds that complete
    each build's own adrp pair to the same .rodata object."""
    facts = {0x3060a2c + i for i, (a, b) in enumerate(zip(PUBLIC.boot_log_add, BODY.boot_log_add)) if a != b}
    facts |= {0x3528810 + i for i, (a, b) in enumerate(zip(PUBLIC.converter_add, BODY.converter_add)) if a != b}
    assert facts == set(BUILD_FACTS)
    sites = tool_spans(build_fixtures.public)
    text = section(build_fixtures.public.ap, '.text')
    pairs, failures = context_check(programs(build_fixtures.public), programs(build_fixtures.body), sites,
                                    text=(text[0], text[0] + text[2]), shifts=shifts,
                                    moved=lambda at: translate(at, BODY), facts=BUILD_FACTS)
    assert [(program, hex(at), reason) for program, at, reason in failures] == []
    assert pairs == RESOLVED_PAIRS
    for use, (adrp, target, body_target) in pairs.items():
        assert target - body_target == 16 and SHIFTS[-1][0] <= target < SHIFTS[-1][1]


# R30's rules on a synthetic pair -------------------------------------------------------------

def adrp_word(at, page, register):
    pages = (page >> 12) - (at >> 12)
    return 0x90000000 | (pages & 3) << 29 | (pages >> 2 & 0x7ffff) << 5 | register


def add_word(register, offset):
    return 0x91000000 | offset << 10 | register << 5 | register   # add xN, xN, #offset


def ldr_word(register, offset):
    return 0xf9400000 | (offset // 8) << 10 | register << 5 | register   # ldr xN, [xN, #offset]


def synthetic(public_add, body_add, *, at=0x1180, data=(b'same data object', b'same data object'), other=None,
              body_use=None):
    """Two 64 KiB programs with one write site at 0x1100+8 and, at `at`, adrp x1 to page 0x8000 then
    add x1 with `public_add` / `body_add` (in the body, the instruction word `body_use` when given). The
    public target holds data[0], the body's data[1]. Shifts are 16 from 0x4000. Returns R30's (pairs,
    failures)."""
    files = []
    for add, object_bytes, use in zip((public_add, body_add), data, (None, body_use)):
        ap = bytearray(0x10000)
        ap[at:at + 8] = struct.pack('<2I', adrp_word(at, 0x8000, 1), add_word(1, add) if use is None else use)
        ap[0x8000 + add:0x8000 + add + 16] = object_bytes
        files.append({'appFw.so': bytes(ap), 'cpapp-b.bin': bytes(0x2000)})
    if other:
        other(*files)
    return context_check(files[0], files[1], [('appFw.so', 0x1100, 8)], text=(0x1000, 0x2000),
                         shifts=[(0, 0x4000, 0), (0x4000, 0x9000, 16)], moved=lambda offset: offset, facts={})


def test_a_pair_to_the_same_shifted_object_is_accepted():
    assert synthetic(0x120, 0x110) == ({0x1184: (0x1180, 0x8120, 0x8110)}, [])


@pytest.mark.parametrize('case, expected', [
    (dict(public_add=0x120, body_add=0x110, data=(b'same data object', b'other bytes here')), 'hold different data'),
    (dict(public_add=0x120, body_add=0x110, data=(bytes(16), bytes(16))), 'hold different data'),
    (dict(public_add=0x120, body_add=0x118, data=(b'same data object', b'same data object')), 'not one address shifted'),
    (dict(public_add=0x120, body_add=0x110, at=0x1100), 'inside a tool-written span'),
    # L166: the same target through another instruction is no shifted copy of the same pair.
    (dict(public_add=0x120, body_add=0x110, body_use=0x91000000 | 0x110 << 10 | 1 << 5 | 2),
     'differ outside the immediate'),
    (dict(public_add=0x120, body_add=0x110, body_use=ldr_word(1, 0x110)), 'differ outside the immediate'),
], ids=['different bytes', 'all zero', 'wrong shift', 'written', 'another destination register', 'add became ldr'])
def test_a_pair_breaking_a_rule_fails(case, expected):
    pairs, failures = synthetic(**case)
    assert pairs == {} and failures and all(expected in reason for _, _, reason in failures)


def test_differences_that_are_not_pairs_fail():
    def other_instruction(public, body):
        public['appFw.so'] = public['appFw.so'][:0x1200] + struct.pack('<I', 0xd503201f) + public['appFw.so'][0x1204:]
        body['cpapp-b.bin'] = b'\1' + body['cpapp-b.bin'][1:]
    pairs, failures = synthetic(0x120, 0x110, other=other_instruction)
    assert [(program, hex(at), reason) for program, at, reason in failures] == [
        ('appFw.so', '0x1200', 'not the same adrp + add/ldr pair in both builds'),
        ('appFw.so', '0x1201', 'not the same adrp + add/ldr pair in both builds'),
        ('appFw.so', '0x1202', 'not the same adrp + add/ldr pair in both builds'),
        ('appFw.so', '0x1203', 'not the same adrp + add/ldr pair in both builds')]
    assert pairs == {0x1184: (0x1180, 0x8120, 0x8110)}


def test_a_build_fact_is_exempt_only_where_named():
    def fact(public, body):
        body['appFw.so'] = body['appFw.so'][:0x1104] + b'\xff' + body['appFw.so'][0x1105:]
    assert synthetic(0x120, 0x110, other=fact)[1] == [('appFw.so', 0x1104, 'inside a tool-written span')]
    files = [{'appFw.so': bytes(0x10000), 'cpapp-b.bin': bytes(16)} for _ in range(2)]
    files[1]['appFw.so'] = bytes(0x1104) + b'\xff' + bytes(0x10000 - 0x1105)
    assert context_check(*files, [('appFw.so', 0x1100, 8)], text=(0x1000, 0x2000), shifts=[],
                         moved=lambda offset: offset, facts={0x1104: 'named fact'}) == ({}, [])


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


def stock_layout():
    """An appFw.so-sized buffer holding just what canonical_windows checks: every canvas root, every
    original image ID, portrait and landscape, and both stock gauge blocks."""
    raw = bytearray(max(max(portrait, landscape) + max(delta, 24) for portrait, landscape, delta, _ in portraitlayout.PAIRS) + 4)
    for portrait, landscape, delta, original in portraitlayout.PAIRS:
        for root, size in ((portrait, 0x028001e0), (landscape, 0x01e00280)):
            struct.pack_into('<6I', raw, root, 0x82, 0xb81, 0x250e, 0, 0, size)
            struct.pack_into('<I', raw, root + delta, original)
    for at, stock in ((portraitgauge.OFFSET, portraitgauge.BEFORE), (portraitgauge.VERTICAL_OFFSET, portraitgauge.VERTICAL_BEFORE)):
        raw[at:at + len(stock)] = stock
    return bytes(raw)


def test_stock_windows_are_the_planned_windows_without_program_bytes():
    """stock_windows needs no appFw.so: it is what canonical_windows plans on stock, in its order."""
    planned = portraitlayout.canonical_windows(stock_layout())
    assert portraitlayout.stock_windows() == [(row['offset'], bytes.fromhex(row['before_hex'])) for row in planned]
    assert len(planned) == VERTICAL_WINDOWS


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
