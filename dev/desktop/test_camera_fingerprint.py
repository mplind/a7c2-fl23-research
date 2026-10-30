"""The read-only program check says which supported Sony 2.01 build the camera's program files are
(buildprofile.identify), and whether they are that build's stock or carry tool changes. It saves them,
the camera's name files and Vertical Display's image files in a new folder, and only reads. Running as
root, it never replaces an earlier capture, never writes or changes ownership through a symbolic link,
and hands back only the files root made.

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

    def read(self, path, missing=False):
        """Like devicesession.Camera.read: an absent file is None when `missing`, else an error."""
        self.reads.append(path)
        if missing and path not in self.files:
            return None
        return self.files[path]

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def __getattr__(self, name):
        raise AssertionError('The check used camera.%s' % name)


IMAGES = ['image_00_32_IPSX.uxc', 'image_01_32_IPSX.uxc', 'image_02_32_IPSX.uxc',
          'image_00_23_IPSX.uxc', 'image_01_23_IPSX.uxc', 'image_02_23_IPSX.uxc']


def files(ap=bytes(range(256)) * 4, cp=b'cp program' * 10):
    return {PATHS['appFw.so']: ap, PATHS['cpapp-b.bin']: cp,
            **{'/usr/share/app/' + name: name.encode() * 3 for name in NAMES + IMAGES}}


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
            digests = sha(ap)[:16], sha(cp)[:16]
            raise buildprofile.UnsupportedFirmware(buildprofile.UNSUPPORTED % digests, digests)
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
        assert (tmp_path / 'resources' / name).stat().st_mode & 0o777 == 0o444
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
    assert identity['digests'] == [sha(files()[PATHS['appFw.so']])[:16], sha(files()[PATHS['cpapp-b.bin']])[:16]]
    assert identity['refused'] == buildprofile.UNSUPPORTED % tuple(identity['digests'])


def test_an_identify_that_fails_is_reported_not_raised(monkeypatch):
    def broken(ap, cp):
        raise ValueError('factory-regions-2.01.json is damaged')
    monkeypatch.setattr(buildprofile, 'identify', broken)
    identity = camera_fingerprint.identity({name: files()[path] for name, path in PATHS.items()})
    assert identity == {'build': None, 'stock': False, 'error': 'factory-regions-2.01.json is damaged'}
    code, text = camera_fingerprint.verdict(identity)
    assert code == 2 and text.startswith('not identified: ')


# As root -----------------------------------------------------------------------------------------

def test_without_root_it_stops_before_any_camera_access(tmp_path, monkeypatch):
    monkeypatch.setattr(camera_fingerprint.os, 'geteuid', lambda: 501)
    camera = ReadOnlyCamera(files())
    with pytest.raises(SystemExit, match='sudo'):
        camera_fingerprint.main(['--out', str(tmp_path / 'out')], camera=camera)
    assert camera.reads == []
    assert not (tmp_path / 'out').exists()


def as_root(monkeypatch, owners, owned_by=lambda path: camera_fingerprint.ROOT_UID):
    """Play root: every file is root's (or `owned_by` says whose), and os.chown records into `owners`."""
    monkeypatch.setattr(camera_fingerprint.os, 'geteuid', lambda: 0)
    monkeypatch.setattr(camera_fingerprint, 'owner', owned_by)

    def chown(path, uid, gid, *, follow_symlinks=True):
        assert follow_symlinks is False
        owners.append((path.name, uid, gid))
    monkeypatch.setattr(camera_fingerprint.os, 'chown', chown)
    monkeypatch.setenv('SUDO_UID', '501')
    monkeypatch.setenv('SUDO_GID', '20')


def run_as_root(tmp_path, monkeypatch, camera, owners=None, out=None):
    owners = [] if owners is None else owners
    as_root(monkeypatch, owners)
    out = tmp_path / 'out' if out is None else out
    code = camera_fingerprint.main(['--out', str(out)], camera=camera)
    return code, out, owners


def test_as_root_it_writes_a_report_and_hands_every_file_back(tmp_path, monkeypatch, capsys):
    camera = ReadOnlyCamera(files())
    identified_as(monkeypatch, playing(BODY, files()))
    code, out, owners = run_as_root(tmp_path, monkeypatch, camera)
    assert code == 0
    # The two programs, then every name file the name tools use, then the image files Vertical Display
    # edits, each read once.
    assert camera.reads == list(PATHS.values()) + ['/usr/share/app/' + name for name in NAMES + IMAGES]
    report = json.loads((out / 'report.json').read_text(encoding='utf-8'))
    assert report['build'] == {'build': BODY.key, 'stock': True}
    assert report['appFw.so']['sha256'] == sha(files()[PATHS['appFw.so']])
    assert sorted(report['resources']) == sorted(NAMES) and len(NAMES) == 68
    assert all((out / 'resources' / name).read_bytes() == name.encode() * 3 for name in NAMES)
    assert sorted(owners) == sorted((name, 501, 20) for name in
                                    ('out', 'appFw.so', 'cpapp-b.bin', 'report.json', 'resources', *NAMES, 'images', *IMAGES))
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


def test_programs_saved_before_a_failed_name_file_read_are_handed_back(tmp_path, monkeypatch):
    # The name files are all read before any is saved: a failed read saves none of them.
    class FailsOnTheSecondName(ReadOnlyCamera):
        def read(self, path):
            if path == '/usr/share/app/' + NAMES[1]:
                raise OSError('USB read failed')
            return super().read(path)
    owners = []
    with pytest.raises(OSError, match='USB read failed'):
        run_as_root(tmp_path, monkeypatch, FailsOnTheSecondName(files()), owners)
    assert sorted(owners) == sorted((name, 501, 20) for name in ('out', 'appFw.so', 'cpapp-b.bin'))
    assert not (tmp_path / 'out/resources').exists()
    assert not (tmp_path / 'out/report.json').exists()


def test_the_vertical_image_files_are_the_ones_vertical_display_edits():
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'src/vertical'))
    from verticaltool import device
    assert sorted(camera_fingerprint.IMAGES) == sorted(IMAGES)
    assert sorted('/usr/share/app/' + name for name in IMAGES) == sorted(device.SOURCES + device.ALIASES)


def test_the_vertical_image_files_are_saved_read_only_with_their_digests(tmp_path, monkeypatch):
    code, out, _ = run_as_root(tmp_path, monkeypatch, ReadOnlyCamera(files()))
    report = json.loads((out / 'report.json').read_text(encoding='utf-8'))
    assert sorted(report['images']) == sorted(IMAGES)
    for name in IMAGES:
        data = name.encode() * 3
        assert (out / 'images' / name).read_bytes() == data
        assert (out / 'images' / name).stat().st_mode & 0o777 == 0o444
        assert report['images'][name] == {'bytes': len(data), 'sha256': sha(data)}


def test_everything_saved_is_read_only(tmp_path, monkeypatch):
    _, out, _ = run_as_root(tmp_path, monkeypatch, ReadOnlyCamera(files()))
    saved = [path for path in out.rglob('*') if path.is_file()]
    assert len(saved) == 2 + 1 + len(NAMES) + len(IMAGES)
    assert all(path.stat().st_mode & 0o777 == 0o444 for path in saved)


def test_report_json_is_written_when_identify_fails(tmp_path, monkeypatch, capsys):
    def broken(ap, cp):
        raise ValueError('factory-regions-2.01.json is damaged')
    monkeypatch.setattr(buildprofile, 'identify', broken)
    code, out, _ = run_as_root(tmp_path, monkeypatch, ReadOnlyCamera(files()))
    assert code == 2 and 'Build: not identified: ' in capsys.readouterr().out
    report = json.loads((out / 'report.json').read_text(encoding='utf-8'))
    assert report['build'] == {'build': None, 'stock': False, 'error': 'factory-regions-2.01.json is damaged'}
    assert report['appFw.so']['sha256'] == sha(files()[PATHS['appFw.so']])


def test_each_run_extends_sys_path_only_once(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, 'path', [path for path in sys.path if path not in map(str, camera_fingerprint.FOLDERS)])
    run_as_root(tmp_path, monkeypatch, ReadOnlyCamera(files()), out=tmp_path / 'first')
    after_one = list(sys.path)
    assert after_one[:len(camera_fingerprint.FOLDERS)] == list(map(str, camera_fingerprint.FOLDERS))
    run_as_root(tmp_path, monkeypatch, ReadOnlyCamera(files()), out=tmp_path / 'second')
    assert sys.path == after_one


# A used or linked --out: refused before the camera is read ------------------------------------------

def refused(tmp_path, monkeypatch, out, reason):
    camera = ReadOnlyCamera(files())
    owners = []
    as_root(monkeypatch, owners)
    with pytest.raises(SystemExit, match=reason) as stop:
        camera_fingerprint.main(['--out', str(out)], camera=camera)
    assert 'Nothing was read; give --out a new folder.' in str(stop.value)
    assert camera.reads == [] and owners == []


@pytest.mark.parametrize('earlier', ['appFw.so', 'cpapp-b.bin', 'report.json', 'resources/' + NAMES[0],
                                     'resources/' + NAMES[-1], 'images/' + IMAGES[0]])
def test_an_out_holding_a_file_this_run_writes_is_refused(tmp_path, monkeypatch, earlier):
    out = tmp_path / 'step-1'
    (out / earlier).parent.mkdir(parents=True, exist_ok=True)
    (out / earlier).write_bytes(b'the step-1 capture')
    refused(tmp_path, monkeypatch, out, 'already holds ' + earlier)
    assert (out / earlier).read_bytes() == b'the step-1 capture'


def test_an_earlier_complete_capture_is_never_replaced(tmp_path, monkeypatch):
    first = files(ap=b'stock body programs' * 10)
    run_as_root(tmp_path, monkeypatch, ReadOnlyCamera(first))
    before = {path: path.read_bytes() for path in (tmp_path / 'out').rglob('*') if path.is_file()}
    refused(tmp_path, monkeypatch, tmp_path / 'out', 'already holds appFw.so, cpapp-b.bin, report.json and %d more'
            % (len(NAMES) + len(IMAGES)))
    assert {path: path.read_bytes() for path in (tmp_path / 'out').rglob('*') if path.is_file()} == before


@pytest.mark.parametrize('where', ['appFw.so', 'resources', 'resources/' + NAMES[0], 'notes/elsewhere'])
@pytest.mark.parametrize('dangling', [False, True], ids=['to a file', 'dangling'])
def test_an_out_holding_a_symbolic_link_is_refused(tmp_path, monkeypatch, where, dangling):
    victim = tmp_path / 'victim'
    if not dangling:
        victim.write_bytes(b'someone else\'s file')
    out = tmp_path / 'out'
    (out / where).parent.mkdir(parents=True, exist_ok=True)
    (out / where).symlink_to(victim)
    refused(tmp_path, monkeypatch, out, 'holds a symbolic link')
    assert victim.read_bytes() == b'someone else\'s file' if not dangling else not victim.exists()


def test_an_out_that_is_a_symbolic_link_is_refused(tmp_path, monkeypatch):
    target = tmp_path / 'fixtures'
    target.mkdir()
    (tmp_path / 'out').symlink_to(target)
    refused(tmp_path, monkeypatch, tmp_path / 'out', 'is a symbolic link')
    assert list(target.iterdir()) == []


def test_an_out_that_is_a_file_is_refused(tmp_path, monkeypatch):
    (tmp_path / 'out').write_bytes(b'a file')
    refused(tmp_path, monkeypatch, tmp_path / 'out', 'is not a folder')


def test_an_empty_existing_folder_is_used(tmp_path, monkeypatch):
    (tmp_path / 'out').mkdir()
    code, out, _ = run_as_root(tmp_path, monkeypatch, ReadOnlyCamera(files()), out=tmp_path / 'out')
    assert (out / 'report.json').is_file()


def test_saving_never_writes_through_a_link_planted_during_the_run(tmp_path, monkeypatch):
    # A link planted after the folder was checked (here, while the camera is read) still is never written
    # through: extract_resources.save refuses it, and nothing else is changed through it.
    victim = tmp_path / 'victim'
    victim.write_bytes(b'someone else\'s file')

    class Planting(ReadOnlyCamera):
        def read(self, path):
            if path == PATHS['cpapp-b.bin']:
                (tmp_path / 'out' / 'cpapp-b.bin').symlink_to(victim)
            return super().read(path)
    owners = []
    with pytest.raises(ValueError, match='symbolic link'):
        run_as_root(tmp_path, monkeypatch, Planting(files()), owners)
    assert victim.read_bytes() == b'someone else\'s file'
    assert sorted(owners) == [('appFw.so', 501, 20), ('out', 501, 20)]


# Handing files back ------------------------------------------------------------------------------

def test_hand_back_skips_links_and_never_follows_them(tmp_path, monkeypatch):
    out = tmp_path / 'out'
    (out / 'resources').mkdir(parents=True)
    (out / 'appFw.so').write_bytes(b'x')
    elsewhere = tmp_path / 'elsewhere'
    elsewhere.mkdir()
    (elsewhere / 'sudoers').write_bytes(b'y')
    (out / 'link-to-file').symlink_to(elsewhere / 'sudoers')
    (out / 'link-to-folder').symlink_to(elsewhere)
    (out / 'dangling').symlink_to(tmp_path / 'missing')
    owners = []
    as_root(monkeypatch, owners)
    camera_fingerprint.hand_back(out, 501, 20)
    assert sorted(owners) == sorted([('out', 501, 20), ('resources', 501, 20), ('appFw.so', 501, 20)])


def test_hand_back_changes_only_what_root_owns(tmp_path, monkeypatch):
    out = tmp_path / 'out'
    out.mkdir()
    (out / 'made-by-this-run').write_bytes(b'x')
    (out / 'someone-elses').write_bytes(b'y')
    owners = []
    as_root(monkeypatch, owners, owned_by=lambda path: 502 if path.name == 'someone-elses' else camera_fingerprint.ROOT_UID)
    camera_fingerprint.hand_back(out, 501, 20)
    assert sorted(owners) == [('made-by-this-run', 501, 20), ('out', 501, 20)]


def test_hand_back_of_a_linked_out_changes_nothing(tmp_path, monkeypatch):
    target = tmp_path / 'target'
    target.mkdir()
    (target / 'file').write_bytes(b'x')
    (tmp_path / 'out').symlink_to(target)
    owners = []
    as_root(monkeypatch, owners)
    camera_fingerprint.hand_back(tmp_path / 'out', 501, 20)
    assert owners == []


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


ALIASES = [name for name in IMAGES if '_23_' in name]


def test_on_a_camera_without_vertical_display_the_alias_images_are_recorded_absent(tmp_path, monkeypatch):
    """Vertical Display creates the image_0N_23 aliases when it installs; a stock camera has none
    (seen on the owner's body, 30 Oct 2026: reading image_00_23 failed with Jiritsu 0x10000006).
    The check records them as absent and still finishes, with the three sources saved."""
    stock = {path: data for path, data in files().items() if not any(path.endswith(name) for name in ALIASES)}
    identified_as(monkeypatch, playing(BODY, stock))
    code, out, _ = run_as_root(tmp_path, monkeypatch, ReadOnlyCamera(stock))
    assert code == 0
    report = json.loads((out / 'report.json').read_text(encoding='utf-8'))
    for name in ALIASES:
        assert report['images'][name] == {'absent': True}
        assert not (out / 'images' / name).exists()
    for name in IMAGES:
        if name not in ALIASES:
            assert (out / 'images' / name).read_bytes() == name.encode() * 3


def test_a_missing_source_image_still_stops_the_check(tmp_path, monkeypatch):
    """The image_0N_32 sources exist on every camera, so a missing one is an error, not 'absent'."""
    broken = {path: data for path, data in files().items() if not path.endswith('image_00_32_IPSX.uxc')}
    with pytest.raises(KeyError):
        run_as_root(tmp_path, monkeypatch, ReadOnlyCamera(broken))
