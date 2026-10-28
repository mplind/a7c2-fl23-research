"""What carries over unchanged to the body build, proven on both Sony 2.01 compiles. Offline only.

Vertical Display writes 19 appFw.so windows, all in .text or in .rodata before 0x4ba1744, which the
body build holds at the same offsets with the same bytes. Factory Restore's regions leave those windows
out, because the vertical tool puts them back itself, so identification normalises a wider set,
buildprofile.identity_regions: without it a camera with Vertical Display installed would no longer
identify, and the firmware gate would refuse every later write, the undo included.

Real-firmware tests read A7C2_BUILD_FIXTURES through conftest.py's build_fixtures and skip when it is
unset. The rest run everywhere on the committed regions files.
"""
import bisect
from pathlib import Path
import sys

import numpy as np
import pytest

from looktool import buildprofile, device_layout, six
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


# Committed tables ----------------------------------------------------------------------------

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
