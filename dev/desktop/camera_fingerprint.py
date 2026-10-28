"""Read-only check that the camera's program files are Sony's stock ILCE-7CM2 2.01.

Usage, as root (the camera's USB service connection needs it):
    sudo env HOME="$HOME" venv/bin/python -I repo/dev/desktop/camera_fingerprint.py --out DIR

It opens the same service session as the app's "Test the service connection", reads
/usr/lib/appFw.so and /cp/cpapp-b.bin, and compares them with the stock 2.01 sizes and SHA-256
digests the app ships in src/looks/assets/runtime-v1.json. It then reads the /usr/share/app/ name
files the name tools use (nameworker.filenames()) into DIR/resources/, so DIR is a complete fixture
build folder for the real-firmware tests (buildfixtures.py). The files and report.json are saved in
DIR and handed back to the sudo user. Nothing is written to the camera.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
RUNTIME = ROOT / 'src/looks/assets/runtime-v1.json'
# A modification found on one body moved two appFw.so pointers 16 bytes before their stock
# targets: the Creative Look jump table (0x4c7cf7c) and a start-up sound string (0x4c14ac3).
# Each probe spans both targets, to show what that modification may have left there.
PROBES = {'appFw.so': ((0x4c7cf6c, 0x20), (0x4c14aa3, 0x30))}
RESOURCES = '/usr/share/app/'


def stock_digests(runtime=RUNTIME):
    asset = json.loads(Path(runtime).read_text(encoding='utf-8'))
    sources = {'appFw.so': asset['ap_sources'], 'cpapp-b.bin': asset['cp_sources']}
    return {name: {key: next(s for s in rows if s['kind'] == 'stock')[key] for key in ('bytes', 'sha256')}
            for name, rows in sources.items()}


def probe(data, at, size):
    return data[at:at + size].hex() if at + size <= len(data) else None


def check(camera, paths, stock, out, probes=PROBES):
    """Read each program once, save it and compare it with the stock size and digest."""
    report = {}
    for name, path in paths.items():
        data = camera.read(path)
        (out / name).write_bytes(data)
        digest = hashlib.sha256(data).hexdigest()
        report[name] = {'bytes': len(data), 'sha256': digest, 'stock': stock[name],
                        'matches_stock': len(data) == stock[name]['bytes'] and digest == stock[name]['sha256'],
                        'probes': {'%#x' % at: probe(data, at, size) for at, size in probes.get(name, ())}}
    return report


def save_resources(camera, names, out):
    """Read each name file once from the camera's /usr/share/app/, save it in out/resources/ and
    report its size and digest."""
    folder = out / 'resources'
    folder.mkdir(exist_ok=True)
    report = {}
    for name in names:
        data = camera.read(RESOURCES + name)
        (folder / name).write_bytes(data)
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
            programs = check(session, PROGRAM_PATHS, stock_digests(), out)
            report = dict(programs, resources=save_resources(session, filenames(), out))
        (out / 'report.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    finally:
        if 'SUDO_UID' in os.environ:
            hand_back(out, int(os.environ['SUDO_UID']), int(os.environ['SUDO_GID']))
    for name, result in programs.items():
        print('%s: %s' % (name, 'matches Sony 2.01' if result['matches_stock'] else 'DIFFERS from Sony 2.01'))
    print('%d name files saved in %s' % (len(report['resources']), out / 'resources'))
    return 0 if all(result['matches_stock'] for result in programs.values()) else 2


if __name__ == '__main__':
    raise SystemExit(main())
