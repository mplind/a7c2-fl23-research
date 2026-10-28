"""The read-only program check says which supported Sony 2.01 build the camera's program files are
(buildprofile.identify), and whether they are that build's stock or carry tool changes. It saves them
and the camera's name files, and only reads.

Exit codes: 0 for a supported build in stock state, 3 for a supported build with tool changes, 2 for
files no supported build explains. Real-firmware cases read A7C2_BUILD_FIXTURES through conftest.py's
build_fixtures and skip when it is unset.
"""
import dataclasses
import hashlib
import json
from pathlib import Path
import sys

import pytest

import camera_fingerprint
from looktool import buildprofile, nameworker

PATHS = {'appFw.so': '/usr/lib/appFw.so', 'cpapp-b.bin': '/cp/cpapp-b.bin'}
NAMES = nameworker.filenames()
PUBLIC, BODY = buildprofile.BUILDS


class ReadOnlyCamera:
    """A camera that serves file reads and refuses every other attribute, so a test fails if the check
    reaches for anything but read."""

    def __init__(self, files):
        self.files, self.reads = files, []

    def read(self, path):
        self.reads.append(path)
        return self.files[path]

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def __getattr__(self, name):
        raise AssertionError('The check used camera.%s' % name)


def files(ap=bytes(range(256)) * 4, cp=b'cp program' * 10):
    return {PATHS['appFw.so']: ap, PATHS['cpapp-b.bin']: cp, **{'/usr/share/app/' + name: name.encode() * 3 for name in NAMES}}


def sha(data):
    return hashlib.sha256(data).hexdigest()


def playing(build, camera_files, stock=True):
    """`build` as identify would return it for `camera_files`: with their digests as its stock digests,
    or with others, as for programs carrying tool changes."""
    ap, cp = camera_files[PATHS['appFw.so']], camera_files[PATHS['cpapp-b.bin']]
    return dataclasses.replace(build, ap_sha256=sha(ap) if stock else '0' * 64, cp_sha256=sha(cp))


def identified_as(monkeypatch, build):
    """Make buildprofile.identify return `build`, or refuse as unsupported when it is None."""
    def identify(ap, cp):
        if build is None:
            raise buildprofile.UnsupportedFirmware(buildprofile.UNSUPPORTED % (sha(ap)[:16], sha(cp)[:16]))
        return build
    monkeypatch.setattr(buildprofile, 'identify', identify)


# Reading and saving --------------------------------------------------------------------------

def test_programs_are_read_once_saved_and_digested_in_full(tmp_path):
    camera = ReadOnlyCamera(files())
    report, programs = camera_fingerprint.check(camera, PATHS, tmp_path, probes={})
    assert camera.reads == ['/usr/lib/appFw.so', '/cp/cpapp-b.bin']
    assert programs == {name: files()[path] for name, path in PATHS.items()}
    for name, path in PATHS.items():
        assert (tmp_path / name).read_bytes() == files()[path]
        assert report[name] == {'bytes': len(files()[path]), 'sha256': sha(files()[path]), 'probes': {}}


def test_probes_show_the_bytes_at_each_offset_and_none_past_the_end(tmp_path):
    probes = {'appFw.so': ((0x10, 4), (1020, 8))}
    report, _ = camera_fingerprint.check(ReadOnlyCamera(files()), PATHS, tmp_path, probes=probes)
    assert report['appFw.so']['probes'] == {'0x10': '10111213', '0x3fc': None}
    assert report['cpapp-b.bin']['probes'] == {}


def test_the_probes_cover_both_moved_pointer_targets_and_their_stock_targets():
    covered = lambda at: any(start <= at < start + size for start, size in camera_fingerprint.PROBES['appFw.so'])
    assert all(covered(at) for at in (0x4c7cf6c, 0x4c7cf7c, 0x4c14ab3, 0x4c14ac3))


def test_name_files_are_saved_under_resources_with_their_digests(tmp_path):
    camera = ReadOnlyCamera(files())
    report = camera_fingerprint.save_resources(camera, NAMES[:3], tmp_path)
    assert camera.reads == ['/usr/share/app/' + name for name in NAMES[:3]]
    assert sorted(path.name for path in (tmp_path / 'resources').iterdir()) == sorted(NAMES[:3])
    for name in NAMES[:3]:
        data = name.encode() * 3
        assert (tmp_path / 'resources' / name).read_bytes() == data
        assert report[name] == {'bytes': len(data), 'sha256': sha(data)}


# Which build -----------------------------------------------------------------------------------

@pytest.mark.parametrize('build', [PUBLIC, BODY], ids=['public', 'body'])
def test_a_supported_build_in_stock_state(monkeypatch, build):
    camera_files = files()
    identified_as(monkeypatch, playing(build, camera_files))
    programs = {name: camera_files[path] for name, path in PATHS.items()}
    identity = camera_fingerprint.identity(programs)
    assert identity == {'build': build.key, 'stock': True}
    assert camera_fingerprint.verdict(identity) == (0, '%s (stock)' % build.key)


def test_a_supported_build_with_tool_changes(monkeypatch):
    camera_files = files()
    identified_as(monkeypatch, playing(BODY, camera_files, stock=False))
    identity = camera_fingerprint.identity({name: camera_files[path] for name, path in PATHS.items()})
    assert identity == {'build': BODY.key, 'stock': False}
    assert camera_fingerprint.verdict(identity) == (3, 'body-2.01-20250923 (tool changes)')


def test_files_no_supported_build_explains(monkeypatch):
    identified_as(monkeypatch, None)
    identity = camera_fingerprint.identity({name: files()[path] for name, path in PATHS.items()})
    assert identity['build'] is None and identity['stock'] is False
    assert sha(files()[PATHS['appFw.so']])[:16] in identity['refused']
    code, text = camera_fingerprint.verdict(identity)
    assert code == 2 and text.startswith('unsupported: ')


def test_stock_means_both_full_digests_are_the_builds_own(monkeypatch):
    """A build that identifies but whose cpapp-b.bin digest differs is not stock either."""
    camera_files = files()
    identified_as(monkeypatch, dataclasses.replace(playing(BODY, camera_files), cp_sha256='0' * 64))
    assert camera_fingerprint.identity({name: camera_files[path] for name, path in PATHS.items()})['stock'] is False


def test_the_real_identify_is_used():
    """Small stand-in programs are no supported build: the refusal is identify's own."""
    identity = camera_fingerprint.identity({name: files()[path] for name, path in PATHS.items()})
    assert identity['build'] is None
    assert buildprofile.unsupported_digests(identity['refused']) == (sha(files()[PATHS['appFw.so']])[:16],
                                                                     sha(files()[PATHS['cpapp-b.bin']])[:16])


# As root -----------------------------------------------------------------------------------------

def test_without_root_it_stops_before_any_camera_access(tmp_path, monkeypatch):
    monkeypatch.setattr(camera_fingerprint.os, 'geteuid', lambda: 501)
    camera = ReadOnlyCamera(files())
    with pytest.raises(SystemExit, match='sudo'):
        camera_fingerprint.main(['--out', str(tmp_path / 'out')], camera=camera)
    assert camera.reads == []
    assert not (tmp_path / 'out').exists()


def run_as_root(tmp_path, monkeypatch, camera, owners=None):
    owners = [] if owners is None else owners
    monkeypatch.setattr(camera_fingerprint.os, 'geteuid', lambda: 0)
    monkeypatch.setattr(camera_fingerprint.os, 'chown', lambda path, uid, gid: owners.append((path.name, uid, gid)))
    monkeypatch.setenv('SUDO_UID', '501')
    monkeypatch.setenv('SUDO_GID', '20')
    out = tmp_path / 'out'
    code = camera_fingerprint.main(['--out', str(out)], camera=camera)
    return code, out, owners


def test_as_root_it_writes_a_report_and_hands_every_file_back(tmp_path, monkeypatch, capsys):
    camera = ReadOnlyCamera(files())
    identified_as(monkeypatch, playing(BODY, files()))
    code, out, owners = run_as_root(tmp_path, monkeypatch, camera)
    assert code == 0
    # The two programs, then every name file the name tools use, each read once: a fixture build folder.
    assert camera.reads == list(PATHS.values()) + ['/usr/share/app/' + name for name in NAMES]
    report = json.loads((out / 'report.json').read_text(encoding='utf-8'))
    assert report['build'] == {'build': BODY.key, 'stock': True}
    assert report['appFw.so']['sha256'] == sha(files()[PATHS['appFw.so']])
    assert sorted(report['resources']) == sorted(NAMES) and len(NAMES) == 68
    assert all((out / 'resources' / name).read_bytes() == name.encode() * 3 for name in NAMES)
    assert sorted(owners) == sorted((name, 501, 20) for name in
                                    ('out', 'appFw.so', 'cpapp-b.bin', 'report.json', 'resources', *NAMES))
    printed = capsys.readouterr().out
    assert 'appFw.so sha256 %s' % sha(files()[PATHS['appFw.so']]) in printed
    assert 'cpapp-b.bin sha256 %s' % sha(files()[PATHS['cpapp-b.bin']]) in printed
    assert 'Build: body-2.01-20250923 (stock)' in printed


@pytest.mark.parametrize('build, stock, code, text', [
    (BODY, False, 3, 'Build: body-2.01-20250923 (tool changes)'),
    (None, False, 2, 'Build: unsupported: '),
], ids=['tool changes', 'unsupported'])
def test_exit_codes_as_root(tmp_path, monkeypatch, capsys, build, stock, code, text):
    identified_as(monkeypatch, build and playing(build, files(), stock=stock))
    result, out, _ = run_as_root(tmp_path, monkeypatch, ReadOnlyCamera(files()))
    assert result == code
    assert text in capsys.readouterr().out
    assert json.loads((out / 'report.json').read_text(encoding='utf-8'))['build']['build'] == (build and build.key)


def test_files_are_handed_back_even_when_a_read_fails(tmp_path, monkeypatch):
    class Failing(ReadOnlyCamera):
        def read(self, path):
            raise OSError('USB read failed')
    owners = []
    with pytest.raises(OSError, match='USB read failed'):
        run_as_root(tmp_path, monkeypatch, Failing(files()), owners)
    assert owners == [('out', 501, 20)]
    assert not (tmp_path / 'out/report.json').exists()


def test_files_saved_before_a_failed_name_file_read_are_handed_back(tmp_path, monkeypatch):
    class FailsOnTheSecondName(ReadOnlyCamera):
        def read(self, path):
            if path == '/usr/share/app/' + NAMES[1]:
                raise OSError('USB read failed')
            return super().read(path)
    owners = []
    with pytest.raises(OSError, match='USB read failed'):
        run_as_root(tmp_path, monkeypatch, FailsOnTheSecondName(files()), owners)
    assert sorted(owners) == sorted((name, 501, 20) for name in ('out', 'appFw.so', 'cpapp-b.bin', 'resources', NAMES[0]))
    assert not (tmp_path / 'out/report.json').exists()


# Real firmware ---------------------------------------------------------------------------------

def vertical_installed(ap):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'src/vertical'))
    from verticaltool import portraitlayout
    return portraitlayout.references(ap, True)[0]


@pytest.mark.parametrize('name, change, code, text', [
    ('body', None, 0, 'Build: body-2.01-20250923 (stock)'),
    ('public', None, 0, 'Build: public-2.01 (stock)'),
    ('body', vertical_installed, 3, 'Build: body-2.01-20250923 (tool changes)'),
    ('hybrid', None, 2, 'Build: unsupported: '),
], ids=['body stock', 'public stock', 'body with vertical display', '27 Oct hybrid'])
def test_real_programs_as_root(build_fixtures, tmp_path, monkeypatch, capsys, name, change, code, text):
    """Task 10 step 1 runs this on the body camera, which must say "body-2.01-20250923 (stock)"."""
    fixture = getattr(build_fixtures, name)
    ap = change(fixture.ap) if change else fixture.ap
    result, out, _ = run_as_root(tmp_path, monkeypatch, ReadOnlyCamera(files(ap, fixture.cp)))
    printed = capsys.readouterr().out
    assert result == code and text in printed
    assert 'appFw.so sha256 %s' % sha(ap) in printed and 'cpapp-b.bin sha256 %s' % fixture.digests[1] in printed
    assert (out / 'appFw.so').read_bytes() == ap
