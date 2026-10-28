"""Read-only check of which supported Sony ILCE-7CM2 2.01 build the camera's program files are.

Usage, as root (the camera's USB service connection needs it):
    sudo env HOME="$HOME" venv/bin/python -I repo/dev/desktop/camera_fingerprint.py --out DIR

It opens the same service session as the app's "Test the service connection" and reads
/usr/lib/appFw.so and /cp/cpapp-b.bin. Then it reads the /usr/share/app/ name files the name tools use
(nameworker.filenames()) into DIR/resources/, so DIR is a complete fixture build folder for the
real-firmware tests (buildfixtures.py). The files and report.json are saved in DIR and handed back to
the sudo user. Nothing is written to the camera.

It prints both programs' full SHA-256 and the build buildprofile.identify finds, the gate the app uses
before any write:
    exit 0  "<build> (stock)": a supported build, both files exactly that build's stock;
    exit 3  "<build> (tool changes)": a supported build whose tool-owned regions hold changes;
    exit 2  "unsupported: …": no supported build explains the files, so the app writes nothing.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
# A modification found on one body moved two appFw.so pointers 16 bytes before their stock
# targets: the Creative Look jump table (0x4c7cf7c) and a start-up sound string (0x4c14ac3).
# Each probe spans both targets, to show what that modification may have left there.
PROBES = {'appFw.so': ((0x4c7cf6c, 0x20), (0x4c14aa3, 0x30))}
RESOURCES = '/usr/share/app/'
STOCK, TOOL_CHANGES, UNSUPPORTED = 0, 3, 2


def probe(data, at, size):
    return data[at:at + size].hex() if at + size <= len(data) else None


def check(camera, paths, out, probes=PROBES):
    """Read each program once and save it. Returns its size, full SHA-256 and probes by name, and the
    programs themselves."""
    report, programs = {}, {}
    for name, path in paths.items():
        data = camera.read(path)
        (out / name).write_bytes(data)
        programs[name] = data
        report[name] = {'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest(),
                        'probes': {'%#x' % at: probe(data, at, size) for at, size in probes.get(name, ())}}
    return report, programs


def identity(programs):
    """{'build': key, 'stock': bool} of the supported build buildprofile.identify finds for
    {'appFw.so': bytes, 'cpapp-b.bin': bytes}; stock when both full-file digests are that build's own.
    {'build': None, 'stock': False, 'refused': message} when identify refuses them."""
    from looktool import buildprofile
    ap, cp = programs['appFw.so'], programs['cpapp-b.bin']
    try:
        build = buildprofile.identify(ap, cp)
    except buildprofile.UnsupportedFirmware as error:
        return {'build': None, 'stock': False, 'refused': str(error)}
    digests = hashlib.sha256(ap).hexdigest(), hashlib.sha256(cp).hexdigest()
    return {'build': build.key, 'stock': digests == (build.ap_sha256, build.cp_sha256)}


def verdict(found):
    """(exit code, text) for an identity(). identify's refusal itself stays in report.json."""
    if found['build'] is None:
        return UNSUPPORTED, 'unsupported: no supported build explains these files, so the app writes nothing'
    if found['stock']:
        return STOCK, '%s (stock)' % found['build']
    return TOOL_CHANGES, '%s (tool changes)' % found['build']


def save_resources(camera, names, out):
    """Read each name file once from the camera's /usr/share/app/, save it read-only (0444) in
    out/resources/ and report its size and digest."""
    folder = out / 'resources'
    folder.mkdir(exist_ok=True)
    report = {}
    for name in names:
        data = camera.read(RESOURCES + name)
        (folder / name).write_bytes(data)
        (folder / name).chmod(0o444)
        report[name] = {'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()}
    return report


def hand_back(out, uid, gid):
    for path in [out, *out.rglob('*')]:
        os.chown(path, uid, gid)


def main(argv=None, camera=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--out', type=Path, required=True)
    out = parser.parse_args(argv).out
    if os.geteuid() != 0:
        raise SystemExit('Run with sudo: the camera service connection needs administrator rights.')
    sys.path[:0] = [str(ROOT / 'src/looks'), str(ROOT / 'src/camera_runtime'), str(ROOT / 'src/camera_runtime/vendor')]
    from looktool.checkpoint import PROGRAM_PATHS
    from looktool.nameworker import filenames
    if camera is None:
        from looktool.devicesession import Camera
        camera = Camera()
    out.mkdir(parents=True, exist_ok=True)
    try:
        with camera as session:
            report, programs = check(session, PROGRAM_PATHS, out)
            report['resources'] = save_resources(session, filenames(), out)
        report['build'] = identity(programs)
        (out / 'report.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    finally:
        if 'SUDO_UID' in os.environ:
            hand_back(out, int(os.environ['SUDO_UID']), int(os.environ['SUDO_GID']))
    for name in PROGRAM_PATHS:
        print('%s sha256 %s' % (name, report[name]['sha256']))
    code, text = verdict(report['build'])
    print('Build: ' + text)
    print('%d name files saved in %s' % (len(report['resources']), out / 'resources'))
    return code


if __name__ == '__main__':
    raise SystemExit(main())
