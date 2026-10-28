"""The read-only program check compares camera files with the stock 2.01 digests, saves them and the
camera's name files, and only reads."""
import hashlib
import json

import pytest

import camera_fingerprint
from looktool import nameworker

PATHS = {'appFw.so': '/usr/lib/appFw.so', 'cpapp-b.bin': '/cp/cpapp-b.bin'}
NAMES = nameworker.filenames()


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


def files():
    return {'/usr/lib/appFw.so': bytes(range(256)) * 4, '/cp/cpapp-b.bin': b'cp program' * 10,
            **{'/usr/share/app/' + name: name.encode() * 3 for name in NAMES}}


def digests(camera_files):
    return {name: {'bytes': len(camera_files[path]), 'sha256': hashlib.sha256(camera_files[path]).hexdigest()}
            for name, path in PATHS.items()}


def test_stock_files_match_and_are_saved(tmp_path):
    camera = ReadOnlyCamera(files())
    report = camera_fingerprint.check(camera, PATHS, digests(files()), tmp_path, probes={})
    assert {name: result['matches_stock'] for name, result in report.items()} == {'appFw.so': True, 'cpapp-b.bin': True}
    assert camera.reads == ['/usr/lib/appFw.so', '/cp/cpapp-b.bin']
    assert (tmp_path / 'appFw.so').read_bytes() == files()['/usr/lib/appFw.so']
    assert (tmp_path / 'cpapp-b.bin').read_bytes() == files()['/cp/cpapp-b.bin']


def test_one_changed_bit_does_not_match(tmp_path):
    changed = files()
    data = bytearray(changed['/usr/lib/appFw.so'])
    data[0x11] ^= 0x40
    changed['/usr/lib/appFw.so'] = bytes(data)
    report = camera_fingerprint.check(ReadOnlyCamera(changed), PATHS, digests(files()), tmp_path, probes={})
    assert report['appFw.so']['matches_stock'] is False
    assert report['cpapp-b.bin']['matches_stock'] is True


def test_a_file_of_the_wrong_size_does_not_match_even_with_the_stock_digest(tmp_path):
    stock = digests(files())
    stock['cpapp-b.bin']['bytes'] += 1
    report = camera_fingerprint.check(ReadOnlyCamera(files()), PATHS, stock, tmp_path, probes={})
    assert report['cpapp-b.bin']['matches_stock'] is False


def test_probes_show_the_bytes_at_each_offset_and_none_past_the_end(tmp_path):
    probes = {'appFw.so': ((0x10, 4), (1020, 8))}
    report = camera_fingerprint.check(ReadOnlyCamera(files()), PATHS, digests(files()), tmp_path, probes=probes)
    assert report['appFw.so']['probes'] == {'0x10': '10111213', '0x3fc': None}
    assert report['cpapp-b.bin']['probes'] == {}


def test_the_stock_digests_are_the_ones_the_app_ships():
    stock = camera_fingerprint.stock_digests()
    assert stock['appFw.so'] == {'bytes': 99960744,
                                 'sha256': '2ea02f7ecbc5bb917316fe8ef4ce5ffd87eb66efaae78ba2ce11420552df539b'}
    assert stock['cpapp-b.bin'] == {'bytes': 18090880,
                                    'sha256': 'f5a477588698ef965748903b8959a39ce4f59ffd4aee4d4234ef1670f56a1428'}


def test_the_probes_cover_both_moved_pointer_targets_and_their_stock_targets():
    covered = lambda at: any(start <= at < start + size for start, size in camera_fingerprint.PROBES['appFw.so'])
    assert all(covered(at) for at in (0x4c7cf6c, 0x4c7cf7c, 0x4c14ab3, 0x4c14ac3))


def test_without_root_it_stops_before_any_camera_access(tmp_path, monkeypatch):
    monkeypatch.setattr(camera_fingerprint.os, 'geteuid', lambda: 501)
    camera = ReadOnlyCamera(files())
    with pytest.raises(SystemExit, match='sudo'):
        camera_fingerprint.main(['--out', str(tmp_path / 'out')], camera=camera)
    assert camera.reads == []
    assert not (tmp_path / 'out').exists()


def run_as_root(tmp_path, monkeypatch, camera, stock, owners=None):
    owners = [] if owners is None else owners
    monkeypatch.setattr(camera_fingerprint.os, 'geteuid', lambda: 0)
    monkeypatch.setattr(camera_fingerprint.os, 'chown', lambda path, uid, gid: owners.append((path.name, uid, gid)))
    monkeypatch.setattr(camera_fingerprint, 'stock_digests', lambda: stock)
    monkeypatch.setenv('SUDO_UID', '501')
    monkeypatch.setenv('SUDO_GID', '20')
    out = tmp_path / 'out'
    code = camera_fingerprint.main(['--out', str(out)], camera=camera)
    return code, out, owners


def test_name_files_are_saved_under_resources_with_their_digests(tmp_path):
    camera = ReadOnlyCamera(files())
    report = camera_fingerprint.save_resources(camera, NAMES[:3], tmp_path)
    assert camera.reads == ['/usr/share/app/' + name for name in NAMES[:3]]
    assert sorted(path.name for path in (tmp_path / 'resources').iterdir()) == sorted(NAMES[:3])
    for name in NAMES[:3]:
        data = name.encode() * 3
        assert (tmp_path / 'resources' / name).read_bytes() == data
        assert report[name] == {'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()}


def test_as_root_it_writes_a_report_and_hands_every_file_back(tmp_path, monkeypatch, capsys):
    camera = ReadOnlyCamera(files())
    code, out, owners = run_as_root(tmp_path, monkeypatch, camera, digests(files()))
    assert code == 0
    # The two programs, then every name file the name tools use, each read once: a fixture build folder.
    assert camera.reads == list(PATHS.values()) + ['/usr/share/app/' + name for name in NAMES]
    report = json.loads((out / 'report.json').read_text(encoding='utf-8'))
    assert report['appFw.so']['matches_stock'] and report['cpapp-b.bin']['matches_stock']
    assert sorted(report['resources']) == sorted(NAMES) and len(NAMES) == 68
    assert all((out / 'resources' / name).read_bytes() == name.encode() * 3 for name in NAMES)
    assert sorted(owners) == sorted((name, 501, 20) for name in
                                    ('out', 'appFw.so', 'cpapp-b.bin', 'report.json', 'resources', *NAMES))
    assert 'appFw.so: matches Sony 2.01' in capsys.readouterr().out


def test_a_differing_file_gives_exit_code_2(tmp_path, monkeypatch, capsys):
    stock = digests(files())
    stock['appFw.so']['sha256'] = '0' * 64
    code, _, _ = run_as_root(tmp_path, monkeypatch, ReadOnlyCamera(files()), stock)
    assert code == 2
    assert 'appFw.so: DIFFERS from Sony 2.01' in capsys.readouterr().out


def test_files_are_handed_back_even_when_a_read_fails(tmp_path, monkeypatch):
    class Failing(ReadOnlyCamera):
        def read(self, path):
            raise OSError('USB read failed')
    owners = []
    with pytest.raises(OSError, match='USB read failed'):
        run_as_root(tmp_path, monkeypatch, Failing(files()), digests(files()), owners)
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
        run_as_root(tmp_path, monkeypatch, FailsOnTheSecondName(files()), digests(files()), owners)
    assert sorted(owners) == sorted((name, 501, 20) for name in ('out', 'appFw.so', 'cpapp-b.bin', 'resources', NAMES[0]))
    assert not (tmp_path / 'out/report.json').exists()
