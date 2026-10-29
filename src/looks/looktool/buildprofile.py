"""Which Sony compile of ILCE-7CM2 2.01 a camera's program files are.

Each supported build has a full-file SHA-256 for appFw.so and cpapp-b.bin, its own table of
tool-owned regions holding that build's stock bytes, and the three facts that differ between builds.
A pair of program files is identified by writing a build's stock bytes over every region a tool may
change (identity_regions), which undoes any tool change, finished or interrupted, and comparing the
whole-file digests. Only the program files take part: settings and calibration never do.

Bytes saved for a later restore (backups, a job's saved windows) record the build they were read
from, and a restore refuses a camera of another build (saved_build, same_build). Offline only; no
camera access.
"""
import base64
import binascii
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import sys
import zlib

ASSETS = Path(__file__).resolve().parents[1] / 'assets'
VERTICAL = Path(__file__).resolve().parents[2] / 'vertical'
PROGRAMS = ('appFw.so', 'cpapp-b.bin')
SCHEMA = 'a7c2-factory-regions/1'
# The name of the built-in factory references (desktopapp.official.load, Factory restore's default):
# every build's regions file, of which a factory reset takes the camera's own build's.
BUILTIN = 'builtin'
LOOK_TABLE_BYTES = 12
# appFw.so .rodata that the body build holds 4 to 16 bytes lower than the public build (translate).
SHIFTED_RODATA = (0x4ba1744, 0x51a09e4)
# Refusals, each a Chinese source string with its English in desktopapp/en_engine.py, which the window
# shows by format. A refusal is raised as a Refusal that carries what it names, and keeps its type into
# the job's status (error_type), so the window tells a refusal from an unknown result by its type.
UNSUPPORTED = '此相机的固件编译版本不受支持，未写入任何内容。（appFw.so %s…，cpapp-b.bin %s…）'
SAVED_OTHER_BUILD = '所保存的内容来自固件编译版本 %s，而相机是 %s，未写入任何内容。'
SAVED_UNIDENTIFIED = '无法确定所保存的内容来自哪个固件编译版本，未写入任何内容。'
REFERENCE_OTHER_BUILD = '所选原厂文件是固件编译版本 %s，而相机是 %s，未写入任何内容。'
REFERENCE_UNSUPPORTED = '所选原厂文件不是受支持的固件编译版本，未写入任何内容。'
JOB_OTHER_BUILD = '此任务记录的固件编译版本是 %s，而相机现在是 %s，没有核对或写入任何内容。'


class Refusal(ValueError):
    """The firmware-build gate refused before anything was written; the message says why."""


class UnsupportedFirmware(Refusal):
    """The program files are not a supported build, so nothing may be written to this camera.
    `digests` holds the two files' SHA-256 prefixes the message names, or None when the message names
    none (the programs were not identified yet)."""

    def __init__(self, message, digests=None):
        super().__init__(message)
        self.digests = digests


class OtherBuild(Refusal):
    """Saved bytes or a factory reference belong to another build than the camera's, or to no
    supported build, so nothing may be written from them. `builds` holds the build keys the message
    names, in its order: the other build's, then the camera's; empty when it names none."""

    def __init__(self, template, *builds):
        super().__init__(template % builds if builds else template)
        self.builds = builds


# The class name (a status file's error_type) of every refusal, including looktool.direct.JobOtherBuild,
# a refusal that is also a ContentChanged. test_refusal_types keeps it equal to Refusal's subclasses.
REFUSAL_TYPES = frozenset({'UnsupportedFirmware', 'OtherBuild', 'JobOtherBuild'})


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


# The public build's look table, from which translate() moves table addresses to another build's.
PUBLIC_LOOK_TABLE = BUILDS[0].look_table


def by_key(key):
    """The supported Build named `key`, or None."""
    return next((build for build in BUILDS if build.key == key), None)


def regions_document(build):
    """The parsed regions file of `build` (its regions_file under src/looks/assets)."""
    return json.loads((ASSETS / build.regions_file).read_text(encoding='utf-8'))


def regions(build):
    """{'appFw.so': [(offset, stock bytes), …], 'cpapp-b.bin': […]}: the build's regions file, the
    tool-owned regions Factory Restore writes back, in file order, holding that build's own stock
    bytes. Vertical Display's windows are not among them: the vertical tool puts those back itself
    (direct.plan), and identity_regions adds them for identification."""
    return decode(regions_document(build), build, build.regions_file)


def decode(document, build, where):
    """{'appFw.so': [(offset, bytes), …], 'cpapp-b.bin': […]} of regions document `document` (schema
    a7c2-factory-regions/1, ILCE-7CM2 2.01) for `build`'s program sizes, in file order. This is the one
    decoder of regions documents: the regions files and Factory Restore's regional references. Refuses
    a program of another size and a region that is out of file order, overlaps another, lies outside its
    program, has a non-integer offset or size, or isn't strict base64 of zlib data of its stated size.
    `where` names the document in errors."""
    if not isinstance(document, dict) or (document.get('schema'), document.get('model'), document.get('version')) != (SCHEMA, 'ILCE-7CM2', '2.01'):
        raise ValueError('%s is not an ILCE-7CM2 2.01 regions file' % where)
    try:
        return {program: _stock_regions(document['programs'][program], size, '%s: %s' % (where, program), build.key)
                for program, size in zip(PROGRAMS, (build.ap_bytes, build.cp_bytes))}
    except (KeyError, TypeError, binascii.Error, zlib.error) as exc:
        raise ValueError('%s is damaged: %r' % (where, exc)) from exc


def color_units(document, where):
    """{CP setting key: {(offset, size): bytes}} of the FL23 colour-unit subranges a regional factory
    reference holds, decoded as strictly as its program regions."""
    try:
        return {int(key): {(at, len(raw)): raw for at, raw in (_inflate(region, '%s: %s' % (where, key)) for region in rows)}
                for key, rows in document['color_units'].items()}
    except (KeyError, TypeError, binascii.Error, zlib.error) as exc:
        raise ValueError('%s is damaged: %r' % (where, exc)) from exc


def encode(raw):
    """A region's zlib_base64 field: what decode reads back as `raw`."""
    return base64.b64encode(zlib.compress(raw, 9)).decode('ascii')


def _inflate(region, where):
    at, count = region['offset'], region['bytes']
    if type(at) is not int or type(count) is not int or at < 0 or count <= 0:
        raise ValueError('%s: invalid region offset or size %r+%r' % (where, at, count))
    raw = zlib.decompress(base64.b64decode(region['zlib_base64'], validate=True))
    if len(raw) != count:
        raise ValueError('%s: region at %#x holds %d bytes, not %d' % (where, at, len(raw), count))
    return at, raw


def _stock_regions(spec, size, where, key):
    if spec['bytes'] != size:
        raise ValueError('%s is %d bytes, but %s has %d' % (where, spec['bytes'], key, size))
    rows, end = [], 0
    for region in spec['regions']:
        at, raw = _inflate(region, where)
        # Regions are in file order, never overlap and lie inside the program.
        if at < end or at + len(raw) > size:
            raise ValueError('%s: invalid region at %#x' % (where, at))
        rows.append((at, raw))
        end = at + len(raw)
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
            raise ValueError('%s: invalid vertical display window %#x+%d' % (key, at, len(raw)))
        holder = next(((start, stock) for start, stock in rows if start <= at and at + len(raw) <= start + len(stock)), None)
        if holder is not None:
            start, stock = holder
            if stock[at - start:at - start + len(raw)] != raw:
                raise ValueError('%s: vertical display window %#x disagrees with its regions file' % (key, at))
            continue
        if any(start < at + len(raw) and at < start + len(stock) for start, stock in result):
            raise ValueError('%s: vertical display window %#x+%d overlaps a tool region' % (key, at, len(raw)))
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
    digests = hashlib.sha256(ap).hexdigest()[:16], hashlib.sha256(cp).hexdigest()[:16]
    raise UnsupportedFirmware(UNSUPPORTED % digests, digests)


def build_of(ap, cp, build=None):
    """`build` when the caller gives one: a job's planners take the build Camera.read_programs identified,
    and never identify again. A standalone or offline caller gives none, and gets the build appFw.so `ap`
    and cpapp-b.bin `cp` are (identify, which refuses programs of no supported build)."""
    return build if build is not None else identify(ap, cp)


def saved_build(recorded, programs):
    """The build that saved bytes (a backup, a job's saved windows) were read from. `recorded` is the
    build key stored with them when they were saved. Bytes saved before keys were stored have None, and
    are identified from `programs`, the {'appFw.so': …, 'cpapp-b.bin': …} saved with them (None when
    none were). Raises OtherBuild (SAVED_UNIDENTIFIED) when neither names a supported build."""
    if recorded is not None:
        build = by_key(recorded)
    elif programs is not None and all(name in programs for name in PROGRAMS):
        try:
            build = identify(programs['appFw.so'], programs['cpapp-b.bin'])
        except UnsupportedFirmware:
            build = None
    else:
        build = None
    if build is None:
        raise OtherBuild(SAVED_UNIDENTIFIED)
    return build


def same_build(saved, camera, refused=SAVED_OTHER_BUILD, kind=OtherBuild):
    """Refuse with kind(refused, saved, camera) unless build key `saved` (the build saved bytes, a
    reference or a job recorded) is `camera`, the camera's identified build's key. Called before
    anything is written from what was saved."""
    if saved != camera:
        raise kind(refused, saved, camera)


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
    """Where a public-build appFw.so offset lies in `build`. In the body build, .rodata from 0x4ba1744 to
    the public build's .rodata end sits 4 to 16 bytes lower (SHIFTED_RODATA; test_port_unchanged derives
    the shifts). The look table there is the one tool address that moves: its 12 bytes and its end bound
    (0x4c7cf7c..0x4c7cf88 inclusive) follow `build.look_table`, so a slice of the table translates whole.
    Any other offset in SHIFTED_RODATA raises ValueError, on every build, rather than give a public address
    for the body: a new tool address there needs its own translation. Every address outside is the same
    in both builds."""
    if PUBLIC_LOOK_TABLE <= offset <= PUBLIC_LOOK_TABLE + LOOK_TABLE_BYTES:
        return offset - PUBLIC_LOOK_TABLE + build.look_table
    if SHIFTED_RODATA[0] <= offset < SHIFTED_RODATA[1]:
        raise ValueError('appFw.so %#x lies in the .rodata the 2.01 builds hold at different addresses; '
                         'no tool address there except the look table has a translation' % offset)
    return offset
