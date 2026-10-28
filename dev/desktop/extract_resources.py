"""Save the name files of Sony's public ILCE-7CM2 2.01 update for the real-firmware tests.

These are the /usr/share/app/ files nameworker.filenames() lists. Usage:
    venv/bin/python repo/dev/desktop/extract_resources.py --source BODYDATA.DAT --out DIR

The fixture folders under A7C2_BUILD_FIXTURES are read-only, so DIR is normally
<A7C2_BUILD_FIXTURES>-resources/public-2.01/, where buildfixtures.resources_folder looks when
public-2.01/ has no resources/ folder of its own. Decodes the update file with the same fwtool readers
Factory Restore's reference uses (desktopapp.official). Reads computer files only: no camera access.
"""
import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'src'), str(ROOT / 'src/looks')]
from desktopapp import official  # noqa: E402
from looktool import nameworker  # noqa: E402

APP = '/share/app/'   # /usr/share/app/ inside the partition image mounted at /usr


def name_files(archive, names):
    """{file name: bytes} of each of `names` under share/app/ in firmware `archive`, in `names` order. A
    name found twice with different bytes, or not at all, is refused."""
    found, where = {}, {}
    for path, stream in official.files(archive, set(names)):
        name = path.rsplit('/', 1)[-1]
        if not path.endswith(APP + name):
            continue
        data = stream.read()
        if name in found and found[name] != data:
            raise ValueError('%s differs between %s and %s' % (name, where[name], path))
        found[name], where[name] = data, path
    missing = [name for name in names if name not in found]
    if missing:
        raise ValueError('The update file lacks %d name files: %s' % (len(missing), ', '.join(missing[:3])))
    return {name: found[name] for name in names}


def save(files, out):
    """Write each {name: bytes} into folder `out`, read-only (0444), as fixtures are. Refuses before
    writing anything when a file there already holds other bytes; the same bytes again are left as
    they are, made read-only."""
    out.mkdir(parents=True, exist_ok=True)
    for name, data in files.items():
        if (out / name).exists() and (out / name).read_bytes() != data:
            raise ValueError('%s already holds other bytes; nothing was written' % (out / name))
    for name, data in files.items():
        if not (out / name).exists():
            (out / name).write_bytes(data)
        (out / name).chmod(0o444)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--source', type=Path, required=True, help='Sony BODYDATA.DAT (or a decrypted FDAT)')
    parser.add_argument('--out', type=Path, required=True, help='folder to receive the name files')
    args = parser.parse_args(argv)
    with official.firmware(args.source) as (_, archive):
        files = name_files(archive, nameworker.filenames())
    save(files, args.out)
    print({'folder': str(args.out), 'files': len(files), 'bytes': sum(map(len, files.values())), 'camera_io': False})


if __name__ == '__main__':
    main()
