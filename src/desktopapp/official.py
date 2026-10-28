"""Prepare a model/version-checked Sony reference locally. Never opens USB."""
from contextlib import contextmanager
import json
from pathlib import Path
import shutil
import stat
import sys
import tarfile
import tempfile
import time
import uuid
from .paths import ROOT, data_root, write_json

MODEL = 0x20030014
FILES = ('appFw.so', 'cpapp-b.bin', 'CX89700_ALLLANG.bin')
VENDOR = ROOT / 'src/desktopapp/vendor'
BUILTIN = 'builtin'


def load(folder=None):
    """The reference Factory Restore writes from. BUILTIN (or None) is the built-in regions of every
    supported build, {'builtin': {build key: builtin(build)}}: the planner (looktool.direct) takes the
    camera's own once its programs are identified. Any other folder is a prepared full Sony 2.01
    reference; its program files are identified, and the build they are is recorded as
    'firmware_build', so the planner uses it only on a camera of that build."""
    from looktool import buildprofile
    if folder is None or str(folder) == BUILTIN:
        return {BUILTIN: {build.key: builtin(build) for build in buildprofile.BUILDS}}
    folder = Path(folder or data_root() / 'factory-2.01')
    pointer = folder / 'current.json'
    if pointer.is_file():
        folder = folder / json.loads(pointer.read_text(encoding='utf-8'))['generation']
    report = json.loads((folder / 'reference.json').read_text(encoding='utf-8'))
    if report.get('model_code') != MODEL or report.get('version') != '2.01':
        raise ValueError('Select original ILCE-7CM2 firmware 2.01')
    values = {name: (folder / name).read_bytes() for name in FILES}
    if any(len(values[name]) != report['sizes'][name] for name in FILES):
        raise ValueError('Incomplete original firmware cache; prepare the Sony file again')
    if values['appFw.so'][:4] != b'\x7fELF' or values['appFw.so'][18:20] != b'\xb7\x00':
        raise ValueError('Original application must be AArch64 ELF')
    try:
        values['firmware_build'] = buildprofile.identify(values['appFw.so'], values['cpapp-b.bin']).key
    except buildprofile.UnsupportedFirmware:
        raise buildprofile.OtherBuild(buildprofile.REFERENCE_UNSUPPORTED) from None
    return values


def builtin(build):
    """The built-in regions document of `build` (its regions_file), recording build.key as
    'firmware_build'."""
    from looktool import buildprofile
    return dict(buildprofile.regions_document(build), firmware_build=build.key)


def _vendor():
    """Make the bundled fwtool importable."""
    if str(VENDOR) not in sys.path:
        sys.path.insert(0, str(VENDOR))


@contextmanager
def firmware(source):
    """(decoder, open tar archive) of the firmware inside Sony ILCE-7CM2 2.01 update file `source`, a
    BODYDATA.DAT or a decrypted FDAT. Decodes on this computer only, into a temporary file, and refuses
    another model or version."""
    _vendor()
    from fwtool.sony import dat, fdat
    print('正在解码原厂文件，仅操作电脑文件…', flush=True)
    with Path(source).open('rb') as stream, tempfile.TemporaryFile() as decoded:
        if stream.read(8) == fdat.fdatHeaderMagic:
            stream.seek(0)
            contents = fdat.readFdat(stream)
            cipher = 'decrypted-FDAT'
            plain = stream
        else:
            stream.seek(0)
            outer = dat.readDat(stream)
            cipher, plain = fdat.decryptFdat(outer.firmwareData)
            header = fdat.FdatHeader.unpack(plain)
            contents = type('Header', (), {'model': header.model,
                'version': '%x.%02x' % (header.versionMajor, header.versionMinor)})()
        if contents.model != MODEL or contents.version != '2.01':
            raise ValueError('Wrong Sony model or version; expected ILCE-7CM2 2.01')
        # Keep streams seekable for the nested tar/filesystem readers.
        plain.seek(0)
        count, last = 0, time.monotonic()
        while block := plain.read(4 * 1024 * 1024):
            decoded.write(block)
            count += len(block)
            if time.monotonic() - last >= 5:
                print('原厂文件已解码 %.0f MiB' % (count / 1048576), flush=True)
                last = time.monotonic()
        decoded.seek(0)
        contents = fdat.readFdat(decoded)
        with tarfile.open(fileobj=contents.firmware, mode='r:') as archive:
            yield cipher, archive


def files(archive, wanted):
    """Yield (path, stream) for every regular file of firmware `archive` whose base name is in `wanted`:
    its own members, then the files inside each 0700_part_image/ ext2 or FAT partition image, whose
    path is the image's member name followed by the path inside it. Each stream is read from the start
    and only until the next file is asked for."""
    _vendor()
    from fwtool.archive import ext2, fat
    for member in archive:
        if not member.isfile():
            continue
        if member.name.rsplit('/', 1)[-1] in wanted:
            yield member.name, archive.extractfile(member)
        elif member.name.startswith('0700_part_image/') and member.size:
            image = archive.extractfile(member)
            reader = ext2.readExt2 if ext2.isExt2(image) else fat.readFat if fat.isFat(image) else None
            for entry in reader(image) if reader else ():
                if stat.S_ISREG(entry.mode) and entry.path.rsplit('/', 1)[-1] in wanted:
                    entry.contents.seek(0)
                    yield member.name + entry.path, entry.contents


def prepare(source, cache=None):
    source = Path(source).expanduser().resolve()
    cache = Path(cache or data_root() / 'factory-2.01')
    if source.is_dir():
        load(source)
        return {'cache': str(source), 'camera_io': False}
    cache.mkdir(parents=True, exist_ok=True)
    generation = 'sony-2.01-' + uuid.uuid4().hex[:12]
    folder = cache / generation
    folder.mkdir()
    with firmware(source) as (cipher, archive):
        for path, contents in files(archive, FILES):
            with (folder / path.rsplit('/', 1)[-1]).open('wb') as out:
                shutil.copyfileobj(contents, out)
            if all((folder / name).is_file() for name in FILES):
                break
    if not all((folder / name).is_file() for name in FILES):
        raise ValueError('Sony archive lacks required original programs/settings')
    report = {'model_code': MODEL, 'version': '2.01', 'decoder': cipher,
              'sizes': {name: (folder / name).stat().st_size for name in FILES}}
    write_json(folder / 'reference.json', report)
    load(folder)
    write_json(cache / 'current.json', {'generation': generation})
    return {'cache': str(cache), 'model': 'ILCE-7CM2', 'firmware': '2.01', 'camera_io': False}
