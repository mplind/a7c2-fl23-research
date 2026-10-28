"""Which Sony compile of ILCE-7CM2 2.01 a camera's program files are.

Each supported build has a full-file SHA-256 for appFw.so and cpapp-b.bin, its own table of
tool-owned regions holding that build's stock bytes, and the three facts that differ between builds.
A pair of program files is identified by writing a build's stock bytes over every region a tool may
change (identity_regions), which undoes any tool change, finished or interrupted, and comparing the
whole-file digests. Only the program files take part: settings and calibration never do. Offline
only; no camera access.
"""
import base64
import binascii
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re
import sys
import zlib

ASSETS = Path(__file__).resolve().parents[1] / 'assets'
VERTICAL = Path(__file__).resolve().parents[2] / 'vertical'
PROGRAMS = ('appFw.so', 'cpapp-b.bin')
PUBLIC_LOOK_TABLE = 0x4c7cf7c
LOOK_TABLE_BYTES = 12
UNSUPPORTED = '此相机的固件版本不受支持，未写入任何内容。（appFw.so %s…，cpapp-b.bin %s…）'
_UNSUPPORTED_MESSAGE = re.compile(re.escape(UNSUPPORTED).replace('%s', '([0-9a-f]{16})'))


class UnsupportedFirmware(ValueError):
    """The program files are not a supported build, so nothing may be written to this camera."""


def unsupported_digests(message):
    """The two digest prefixes an UNSUPPORTED refusal names, so the window can show it translated;
    None for any other message."""
    match = _UNSUPPORTED_MESSAGE.fullmatch(message)
    return match.groups() if match else None


@dataclass(frozen=True)
class Build:
    key: str
    label_zh: str
    ap_sha256: str
    cp_sha256: str
    ap_bytes: int
    cp_bytes: int
    look_table: int        # appFw.so offset of the 12-byte look table
    converter_add: bytes   # stock instruction at appFw.so 0x3528810 (add x0,x0,#table)
    boot_log_add: bytes    # stock instruction at appFw.so 0x3060a2c (start-up sound log)
    regions_file: str      # file name under src/looks/assets


BUILDS = (
    Build(key='public-2.01', label_zh='Sony 2.01（公开更新）',
          ap_sha256='2ea02f7ecbc5bb917316fe8ef4ce5ffd87eb66efaae78ba2ce11420552df539b',
          cp_sha256='f5a477588698ef965748903b8959a39ce4f59ffd4aee4d4234ef1670f56a1428',
          ap_bytes=99960744, cp_bytes=18090880, look_table=0x4c7cf7c,
          converter_add=bytes.fromhex('00f03d91'), boot_log_add=bytes.fromhex('000c2b91'),
          regions_file='factory-regions-2.01.json'),
    Build(key='body-2.01-20250923', label_zh='Sony 2.01（机身版本，2025 年 9 月 23 日）',
          ap_sha256='77fa856ed5812124ffec507857ec48af43159357b2c8a341cb15f3d5c1076d54',
          cp_sha256='171f6d7c0b95c6bea3b64487d0b826f38a94ec92ca3984679a0ee2899e704efa',
          ap_bytes=99960744, cp_bytes=18090880, look_table=0x4c7cf6c,
          converter_add=bytes.fromhex('00b03d91'), boot_log_add=bytes.fromhex('00cc2a91'),
          regions_file='factory-regions-2.01-body-20250923.json'),
)


def regions(build):
    """{'appFw.so': [(offset, stock bytes), …], 'cpapp-b.bin': […]}: the build's regions file, the
    tool-owned regions Factory Restore writes back, in file order, holding that build's own stock
    bytes. Vertical Display's windows are not among them: the vertical tool puts those back itself
    (direct.plan), and identity_regions adds them for identification."""
    name = build.regions_file
    data = json.loads((ASSETS / name).read_text(encoding='utf-8'))
    if (data.get('schema'), data.get('model'), data.get('version')) != ('a7c2-factory-regions/1', 'ILCE-7CM2', '2.01'):
        raise ValueError('%s is not an ILCE-7CM2 2.01 regions file' % name)
    try:
        return {program: _stock_regions(data['programs'][program], size, '%s: %s' % (name, program), build.key)
                for program, size in zip(PROGRAMS, (build.ap_bytes, build.cp_bytes))}
    except (KeyError, TypeError, binascii.Error, zlib.error) as exc:
        raise ValueError('%s is damaged: %r' % (name, exc)) from exc


def _stock_regions(spec, size, where, key):
    if spec['bytes'] != size:
        raise ValueError('%s is %d bytes, but %s has %d' % (where, spec['bytes'], key, size))
    rows, end = [], 0
    for region in spec['regions']:
        at, count = region['offset'], region['bytes']
        raw = zlib.decompress(base64.b64decode(region['zlib_base64'], validate=True))
        # Regions are in file order, never overlap and lie inside the program.
        if len(raw) != count or count <= 0 or at < end or at + count > size:
            raise ValueError('%s: invalid region at %#x' % (where, at))
        rows.append((at, raw))
        end = at + count
    return rows


def vertical_display_windows():
    """(offset, stock bytes) of every appFw.so window Vertical Display writes (verticaltool.portraitlayout).
    They lie in .text and in .rodata before 0x4ba1744, which both 2.01 builds hold at the same offsets
    with the same bytes, so one list serves every build (test_port_unchanged.py proves it)."""
    if str(VERTICAL) not in sys.path:
        sys.path.insert(0, str(VERTICAL))
    from verticaltool import portraitlayout
    return portraitlayout.stock_windows()


def identity_regions(build):
    """{'appFw.so': [(offset, stock bytes), …], 'cpapp-b.bin': […]}: every program region any tool may
    change on `build`, in file order, holding the build's stock bytes. This is the set identify()
    normalises: regions(build) together with the Vertical Display windows."""
    result = regions(build)
    result['appFw.so'] = _with_windows(result['appFw.so'], vertical_display_windows(), build.ap_bytes, build.key)
    return result


def _with_windows(rows, windows, size, key):
    """`rows` and each (offset, stock bytes) window, in file order. A window that already lies inside
    one row is taken once, and must hold the same bytes there; one that overlaps a row only in part,
    is empty or lies outside the program is refused."""
    result = list(rows)
    for at, raw in windows:
        if not raw or at < 0 or at + len(raw) > size:
            raise ValueError('%s: invalid Vertical Display window %#x+%d' % (key, at, len(raw)))
        holder = next(((start, stock) for start, stock in rows if start <= at and at + len(raw) <= start + len(stock)), None)
        if holder is not None:
            start, stock = holder
            if stock[at - start:at - start + len(raw)] != raw:
                raise ValueError('%s: Vertical Display window %#x disagrees with its regions file' % (key, at))
            continue
        if any(start < at + len(raw) and at < start + len(stock) for start, stock in result):
            raise ValueError('%s: Vertical Display window %#x+%d overlaps a tool region' % (key, at, len(raw)))
        result.append((at, raw))
    return sorted(result)


def _normalised_sha256(program, stock_regions):
    restored = bytearray(program)
    for at, raw in stock_regions:
        restored[at:at + len(raw)] = raw
    return hashlib.sha256(restored).hexdigest()


def identify(ap, cp):
    """The supported build that appFw.so `ap` and cpapp-b.bin `cp` are, whatever the tools' regions
    (identity_regions) hold. Raises UnsupportedFirmware naming the files' own digests when no build
    matches."""
    for build in BUILDS:
        if len(ap) != build.ap_bytes or len(cp) != build.cp_bytes:
            continue
        stock_regions = identity_regions(build)
        # cpapp-b.bin is the smaller file and already tells the two 2.01 builds apart.
        if (_normalised_sha256(cp, stock_regions['cpapp-b.bin']) == build.cp_sha256
                and _normalised_sha256(ap, stock_regions['appFw.so']) == build.ap_sha256):
            return build
    observed = hashlib.sha256(ap).hexdigest(), hashlib.sha256(cp).hexdigest()
    raise UnsupportedFirmware(UNSUPPORTED % (observed[0][:16], observed[1][:16]))


def stock(build, program, offset, size):
    """The build's stock bytes at offset..offset+size of one program, in that build's own addresses.
    The span must lie inside a single tool-owned region."""
    if program not in PROGRAMS:
        raise ValueError('Unknown program file: %s' % program)
    if size <= 0:
        raise ValueError('Empty stock span at %s %#x' % (program, offset))
    for at, raw in regions(build)[program]:
        if at <= offset and offset + size <= at + len(raw):
            return raw[offset - at:offset - at + size]
    raise ValueError('%s has no stock bytes for %s %#x+%d: outside its tool regions' % (build.key, program, offset, size))


def translate(offset, build):
    """Where a public-build appFw.so offset lies in `build`. Only the look table moves: its 12 bytes
    and its end bound (0x4c7cf7c..0x4c7cf88 inclusive) follow `build.look_table`, so a slice of the
    table translates whole. Every other address is the same in both builds."""
    if PUBLIC_LOOK_TABLE <= offset <= PUBLIC_LOOK_TABLE + LOOK_TABLE_BYTES:
        return offset - PUBLIC_LOOK_TABLE + build.look_table
    return offset
