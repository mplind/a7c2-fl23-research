"""The name-file fixtures the real-firmware tests compare: where they are found, and how the public ones
are pulled from Sony's update file. Offline only; no camera access and no real BODYDATA.DAT.

The fixture folders under A7C2_BUILD_FIXTURES are read-only, so a build's name files live either in
its own resources/ folder (a camera capture made by camera_fingerprint.py) or in
<A7C2_BUILD_FIXTURES>-resources/<build>/ beside it (extract_resources.py's output for the public build).
"""
from contextlib import contextmanager
import io
import json

import pytest

import buildfixtures
import extract_resources
from desktopapp import official

NAMES = ['string_alpha_horizontal.uxc', 'string_beta_vertical.uxc']


def put(folder, files):
    folder.mkdir(parents=True, exist_ok=True)
    for name, data in files.items():
        (folder / name).write_bytes(data)


# Where a build's name files are found ------------------------------------------------------

def test_a_builds_own_resources_folder_comes_first(tmp_path):
    fixtures = tmp_path / 'build-fixtures'
    put(fixtures / 'body/resources', {name: b'camera ' + name.encode() for name in NAMES})
    put(tmp_path / 'build-fixtures-resources/body', {name: b'beside' for name in NAMES})
    assert buildfixtures.resources_folder(fixtures, 'body') == fixtures / 'body/resources'
    assert buildfixtures.resources(fixtures, 'body', NAMES) == {name: b'camera ' + name.encode() for name in NAMES}


def test_otherwise_the_folder_beside_the_read_only_fixtures_is_used(tmp_path):
    fixtures = tmp_path / 'build-fixtures'
    (fixtures / 'public').mkdir(parents=True)
    put(tmp_path / 'build-fixtures-resources/public', {name: name.encode() for name in NAMES})
    assert buildfixtures.resources_folder(str(fixtures) + '/', 'public') == tmp_path / 'build-fixtures-resources/public'
    assert buildfixtures.resources(fixtures, 'public', NAMES) == {name: name.encode() for name in NAMES}


def test_a_build_without_name_files_has_none(tmp_path):
    (tmp_path / 'build-fixtures/body').mkdir(parents=True)
    assert buildfixtures.resources_folder(tmp_path / 'build-fixtures', 'body') is None
    assert buildfixtures.resources(tmp_path / 'build-fixtures', 'body', NAMES) is None


def test_a_resources_folder_missing_a_name_file_is_refused(tmp_path):
    fixtures = tmp_path / 'build-fixtures'
    put(fixtures / 'body/resources', {NAMES[0]: b'one'})
    with pytest.raises(ValueError, match=NAMES[1]):
        buildfixtures.resources(fixtures, 'body', NAMES)


# Pulling the public name files from the update file ----------------------------------------

def walked(entries):
    """official.files over a fake firmware: yields the (path, bytes) `entries` whose base name it asks for."""
    def files(archive, wanted):
        assert archive == 'archive'
        for path, data in entries:
            if path.rsplit('/', 1)[-1] in wanted:
                yield path, io.BytesIO(data)
    return files


def test_name_files_come_from_share_app_only(monkeypatch):
    image = '0700_part_image/dev/nflashc'
    monkeypatch.setattr(extract_resources.official, 'files', walked([
        (image + '/share/app/' + NAMES[0], b'first'),
        (image + '/share/other/' + NAMES[1], b'not a name file'),
        (image + '/share/app/' + NAMES[1], b'second'),
        (image + '/share/app/unlisted.uxc', b'unlisted')]))
    assert extract_resources.name_files('archive', NAMES) == {NAMES[0]: b'first', NAMES[1]: b'second'}


def test_a_name_file_found_twice_must_hold_the_same_bytes(monkeypatch):
    twice = [('0700_part_image/a/share/app/' + NAMES[0], b'same'), ('0700_part_image/b/share/app/' + NAMES[0], b'same'),
             ('0700_part_image/a/share/app/' + NAMES[1], b'x')]
    monkeypatch.setattr(extract_resources.official, 'files', walked(twice))
    assert extract_resources.name_files('archive', NAMES)[NAMES[0]] == b'same'
    twice[1] = ('0700_part_image/b/share/app/' + NAMES[0], b'other')
    with pytest.raises(ValueError, match='0700_part_image/b/share/app/' + NAMES[0]):
        extract_resources.name_files('archive', NAMES)


def test_a_missing_name_file_is_refused(monkeypatch):
    monkeypatch.setattr(extract_resources.official, 'files', walked([('0700_part_image/a/share/app/' + NAMES[0], b'x')]))
    with pytest.raises(ValueError, match=NAMES[1]):
        extract_resources.name_files('archive', NAMES)


def test_save_never_replaces_other_bytes(tmp_path):
    out = tmp_path / 'resources/public-2.01'
    extract_resources.save({NAMES[0]: b'one'}, out)
    extract_resources.save({NAMES[0]: b'one'}, out)   # the same bytes again: nothing to do
    with pytest.raises(ValueError, match=NAMES[0]):
        extract_resources.save({NAMES[1]: b'two', NAMES[0]: b'changed'}, out)
    assert (out / NAMES[0]).read_bytes() == b'one'
    assert not (out / NAMES[1]).exists()


def test_main_decodes_the_source_and_saves_every_listed_name_file(tmp_path, monkeypatch, capsys):
    opened = []

    @contextmanager
    def firmware(source):
        opened.append(source)
        yield 'cipher', 'archive'
    monkeypatch.setattr(extract_resources.official, 'firmware', firmware)
    monkeypatch.setattr(extract_resources.official, 'files',
                        walked([('0700_part_image/a/share/app/' + name, name.encode()) for name in NAMES]))
    monkeypatch.setattr(extract_resources.nameworker, 'filenames', lambda: NAMES)
    out = tmp_path / 'out'
    extract_resources.main(['--source', str(tmp_path / 'BODYDATA.DAT'), '--out', str(out)])
    assert opened == [tmp_path / 'BODYDATA.DAT']
    assert sorted(path.name for path in out.iterdir()) == NAMES
    assert all((out / name).read_bytes() == name.encode() for name in NAMES)
    assert "'camera_io': False" in capsys.readouterr().out


# official.prepare over the same walk -------------------------------------------------------

def test_prepare_writes_the_three_reference_files_and_stops_reading(tmp_path, monkeypatch):
    program = b'\x7fELF' + bytes(14) + b'\xb7\x00' + bytes(12)
    found = [('0700_part_image/a/lib/appFw.so', program), ('cpapp-b.bin', b'cp'),
             ('0700_part_image/b/CX89700_ALLLANG.bin', b'settings')]

    def files(archive, wanted):
        assert archive == 'archive' and set(wanted) == set(official.FILES)
        for path, data in found:
            yield path, io.BytesIO(data)
        raise AssertionError('prepare read past the last file it needed')

    @contextmanager
    def firmware(source):
        assert source == tmp_path / 'BODYDATA.DAT'
        yield 'CXD90057_k8', 'archive'
    monkeypatch.setattr(official, 'firmware', firmware)
    monkeypatch.setattr(official, 'files', files)
    (tmp_path / 'BODYDATA.DAT').write_bytes(b'')
    result = official.prepare(tmp_path / 'BODYDATA.DAT', tmp_path / 'cache')
    assert result == {'cache': str(tmp_path / 'cache'), 'model': 'ILCE-7CM2', 'firmware': '2.01', 'camera_io': False}
    generation = json.loads((tmp_path / 'cache/current.json').read_text(encoding='utf-8'))['generation']
    folder = tmp_path / 'cache' / generation
    assert {name: (folder / name).read_bytes() for name in official.FILES} == {
        'appFw.so': program, 'cpapp-b.bin': b'cp', 'CX89700_ALLLANG.bin': b'settings'}
    assert json.loads((folder / 'reference.json').read_text(encoding='utf-8'))['decoder'] == 'CXD90057_k8'
    assert official.load(tmp_path / 'cache')['cpapp-b.bin'] == b'cp'


def test_files_reads_members_and_partition_images(monkeypatch):
    """official.files over a real tar holding one wanted member and one FAT/ext2 stand-in image."""
    import stat
    import tarfile
    from types import SimpleNamespace
    raw = io.BytesIO()
    with tarfile.open(fileobj=raw, mode='w') as archive:
        for name, data in (('top/cpapp-b.bin', b'cp'), ('0700_part_image/dev/blk', b'IMAGE'), ('other/x', b'x')):
            info = tarfile.TarInfo(name)
            info.size = len(data)
            archive.addfile(info, io.BytesIO(data))
    raw.seek(0)
    entries = [SimpleNamespace(path='/lib/appFw.so', mode=stat.S_IFREG, contents=io.BytesIO(b'ap')),
               SimpleNamespace(path='/lib', mode=stat.S_IFDIR, contents=None),
               SimpleNamespace(path='/share/app/appFw.so', mode=stat.S_IFLNK, contents=io.BytesIO(b'link'))]
    official._vendor()
    from fwtool.archive import ext2, fat
    monkeypatch.setattr(ext2, 'isExt2', lambda image: image.read(5) == b'IMAGE')
    monkeypatch.setattr(ext2, 'readExt2', lambda image: iter(entries))
    monkeypatch.setattr(fat, 'isFat', lambda image: False)
    with tarfile.open(fileobj=raw, mode='r:') as archive:
        found = [(path, stream.read()) for path, stream in official.files(archive, {'appFw.so', 'cpapp-b.bin'})]
    assert found == [('top/cpapp-b.bin', b'cp'), ('0700_part_image/dev/blk/lib/appFw.so', b'ap')]
