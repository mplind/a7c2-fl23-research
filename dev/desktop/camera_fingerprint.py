"""Read-only check of which supported Sony ILCE-7CM2 2.01 build the camera's program files are.

Usage, as root (the camera's USB service connection needs it), with a new folder for each run:
    sudo env HOME="$HOME" venv/bin/python -I repo/dev/desktop/camera_fingerprint.py --out NEW-FOLDER

It opens the same service session as the app's Test button (Service connection) and reads
/usr/lib/appFw.so and /cp/cpapp-b.bin. Then it reads the /usr/share/app/ name files the name tools use
(nameworker.filenames()) into DIR/resources/, and the six image files Vertical Display edits (IMAGES)
into DIR/images/. The files and report.json are saved read-only in DIR, and the files this run made are
handed back to the sudo user. Nothing is written to the camera.

DIR must be new or empty: a folder that already holds a file this run writes, or any symbolic link, or
that is a symbolic link itself, is refused before the camera is read, so an earlier capture is never
replaced. Never point --out at a fixture folder under A7C2_BUILD_FIXTURES: copy a checked capture's
name files to <A7C2_BUILD_FIXTURES>-resources/<build>/ instead (buildfixtures.py).

It prints both programs' full SHA-256 and the build buildprofile.identify finds, the gate the app uses
before any write:
    exit 0  "<build> (stock)": a supported build, both files exactly that build's stock;
    exit 3  "<build> (tool changes)": a supported build whose tool-owned regions hold changes;
    exit 2  "unsupported: …": no supported build explains the files, so the app writes nothing;
            "not identified: …": identify itself failed (its error is in report.json), so the app
            writes nothing either.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
# What main() puts first on sys.path, once: the app's packages, and this folder for extract_resources
# (python -I adds no script folder).
FOLDERS = (HERE, ROOT / 'src/looks', ROOT / 'src/camera_runtime', ROOT / 'src/camera_runtime/vendor')
# A modification found on one body moved two appFw.so pointers 16 bytes before their stock
# targets: the Creative Look jump table (0x4c7cf7c) and a start-up sound string (0x4c14ac3).
# Each probe spans both targets, to show what that modification may have left there.
PROBES = {'appFw.so': ((0x4c7cf6c, 0x20), (0x4c14aa3, 0x30))}
RESOURCES = '/usr/share/app/'
# The image banks Vertical Display edits (verticaltool.device SOURCES and ALIASES), read only.
IMAGES = tuple('image_%02d_%s_IPSX.uxc' % (index, kind) for kind in ('32', '23') for index in range(3))
STOCK, TOOL_CHANGES, UNSUPPORTED = 0, 3, 2
ROOT_UID = 0


def import_path():
    """Put FOLDERS first on sys.path, each once, however often main() runs."""
    for folder in reversed(FOLDERS):
        if str(folder) not in sys.path:
            sys.path.insert(0, str(folder))


def written(names):
    """Every path, relative to --out, that a run writes when the camera's name files are `names`."""
    return [Path('appFw.so'), Path('cpapp-b.bin'), Path('report.json'),
            *(Path('resources', name) for name in names), *(Path('images', name) for name in IMAGES)]


def refuse_used(out, names):
    """Stop, before the camera is read, when folder `out` is a symbolic link, is not a folder, holds a
    symbolic link anywhere, or holds a file this run writes: each run gets a new folder."""
    if out.is_symlink():
        raise SystemExit('%s is a symbolic link. Nothing was read; give --out a new folder.' % out)
    if not out.exists():
        return
    if not out.is_dir():
        raise SystemExit('%s is not a folder. Nothing was read; give --out a new folder.' % out)
    for directory, folders, files in os.walk(out, followlinks=False):
        for name in folders + files:
            if (Path(directory) / name).is_symlink():
                raise SystemExit('%s holds a symbolic link, %s. Nothing was read; give --out a new folder.'
                                 % (out, Path(directory) / name))
    used = [str(path) for path in written(names) if os.path.lexists(out / path)]
    if used:
        raise SystemExit('%s already holds %s from an earlier run. Nothing was read; give --out a new folder.'
                         % (out, ', '.join(used[:3]) + (' and %d more' % (len(used) - 3) if len(used) > 3 else '')))


def probe(data, at, size):
    return data[at:at + size].hex() if at + size <= len(data) else None


def save(files, out):
    """Save {name: bytes} in folder `out`, read-only, through extract_resources.save, which never
    replaces other bytes, a symbolic link or a file it did not write."""
    from extract_resources import save as save_read_only
    save_read_only(files, out)


def check(camera, paths, out, probes=PROBES):
    """Read each program once and save it. Returns its size, full SHA-256 and probes by name, and the
    programs themselves."""
    report, programs = {}, {}
    for name, path in paths.items():
        data = camera.read(path)
        save({name: data}, out)
        programs[name] = data
        report[name] = {'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest(),
                        'probes': {'%#x' % at: probe(data, at, size) for at, size in probes.get(name, ())}}
    return report, programs


def identity(programs):
    """{'build': key, 'stock': bool} of the supported build buildprofile.identify finds for
    {'appFw.so': bytes, 'cpapp-b.bin': bytes}; stock when both full-file digests are that build's own.
    {'build': None, 'stock': False, 'refused': message, 'digests': [ap, cp]} when identify refuses them,
    with the digest prefixes it names; {'build': None, 'stock': False, 'error': message} when identify
    itself fails (a damaged regions file, say)."""
    from looktool import buildprofile
    ap, cp = programs['appFw.so'], programs['cpapp-b.bin']
    try:
        build = buildprofile.identify(ap, cp)
    except buildprofile.UnsupportedFirmware as error:
        return {'build': None, 'stock': False, 'refused': str(error), 'digests': list(error.digests)}
    except ValueError as error:
        return {'build': None, 'stock': False, 'error': str(error)}
    digests = hashlib.sha256(ap).hexdigest(), hashlib.sha256(cp).hexdigest()
    return {'build': build.key, 'stock': digests == (build.ap_sha256, build.cp_sha256)}


def verdict(found):
    """(exit code, text) for an identity(). identify's refusal or error itself stays in report.json."""
    if 'error' in found:
        return UNSUPPORTED, 'not identified: identify failed (see report.json), so the app writes nothing'
    if found['build'] is None:
        return UNSUPPORTED, 'unsupported: no supported build explains these files, so the app writes nothing'
    if found['stock']:
        return STOCK, '%s (stock)' % found['build']
    return TOOL_CHANGES, '%s (tool changes)' % found['build']


def save_files(camera, folder, names, out):
    """Read each of `names` once from the camera's folder `folder`, save them read-only (0444) in
    `out`, and report each one's size and digest."""
    files = {name: camera.read(folder + name) for name in names}
    save(files, out)
    return {name: {'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()} for name, data in files.items()}


def save_resources(camera, names, out):
    """The camera's /usr/share/app/ name files `names`, saved in out/resources/ (see save_files)."""
    return save_files(camera, RESOURCES, names, out / 'resources')


def save_images(camera, out):
    """The camera's /usr/share/app/ image banks IMAGES, saved in out/images/ (see save_files)."""
    return save_files(camera, RESOURCES, IMAGES, out / 'images')


def owner(path):
    """The user id that owns `path` itself; a symbolic link is not followed."""
    return path.lstat().st_uid


def hand_back(out, uid, gid):
    """Give the sudo user the files and folders under `out` that root owns, as
    macos_authorization.return_ownership does: a symbolic link is skipped, never followed, and a file
    someone else owns keeps its owner."""
    if out.is_symlink() or not out.is_dir():
        return
    for directory, folders, files in os.walk(out, followlinks=False):
        folders[:] = [name for name in folders if not (Path(directory) / name).is_symlink()]
        for path in [Path(directory)] + [Path(directory) / name for name in files]:
            if not path.is_symlink() and owner(path) == ROOT_UID:
                os.chown(path, uid, gid, follow_symlinks=False)


def main(argv=None, camera=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--out', type=Path, required=True, help='a new folder for this run')
    out = parser.parse_args(argv).out
    if os.geteuid() != 0:
        raise SystemExit('Run with sudo: the camera service connection needs administrator rights.')
    import_path()
    from looktool.checkpoint import PROGRAM_PATHS
    from looktool.nameworker import filenames
    refuse_used(out, filenames())
    if camera is None:
        from looktool.devicesession import Camera
        camera = Camera()
    out.mkdir(parents=True, exist_ok=True)
    try:
        with camera as session:
            report, programs = check(session, PROGRAM_PATHS, out)
            report['resources'] = save_resources(session, filenames(), out)
            report['images'] = save_images(session, out)
        report['build'] = identity(programs)
        save({'report.json': (json.dumps(report, indent=2) + '\n').encode('utf-8')}, out)
    finally:
        if 'SUDO_UID' in os.environ:
            hand_back(out, int(os.environ['SUDO_UID']), int(os.environ['SUDO_GID']))
    for name in PROGRAM_PATHS:
        print('%s sha256 %s' % (name, report[name]['sha256']))
    code, text = verdict(report['build'])
    print('Build: ' + text)
    print('%d name files saved in %s, %d image files in %s' % (
        len(report['resources']), out / 'resources', len(report['images']), out / 'images'))
    return code


if __name__ == '__main__':
    raise SystemExit(main())
