"""Build the body build's factory regions from the public table and the body's own program files.

Every region keeps its public offset and size, except the look table, which moves to the body
build's address. Each region's bytes are the body's stock bytes there; color_units are unchanged.
Reads computer files only: no camera access.
"""
import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'src/looks')]
from looktool import buildprofile

PUBLIC, BODY = (buildprofile.by_key(key) for key in ('public-2.01', 'body-2.01-20250923'))


def reference(ap, cp, public):
    """The body regions document: `public`'s regions, moved and refilled from body programs ap/cp."""
    programs = dict(zip(buildprofile.PROGRAMS, (ap, cp)))
    for name, size, digest in zip(buildprofile.PROGRAMS, (BODY.ap_bytes, BODY.cp_bytes), (BODY.ap_sha256, BODY.cp_sha256)):
        if len(programs[name]) != size or hashlib.sha256(programs[name]).hexdigest() != digest:
            raise ValueError('%s is not the %s program file' % (name, BODY.key))
    output = {'schema': public['schema'], 'model': public['model'], 'version': public['version'],
              'source': 'Sony ILCE-7CM2 2.01 camera build %s (appFw.so %s, cpapp-b.bin %s), program files '
                        'read from the camera' % (BODY.key, BODY.ap_sha256[:16], BODY.cp_sha256[:16]),
              'scope': public['scope'], 'programs': {}, 'color_units': public['color_units']}
    for name in buildprofile.PROGRAMS:
        rows = []
        for region in public['programs'][name]['regions']:
            at, size = region['offset'], region['bytes']
            if name == 'appFw.so':
                # A region must move whole or not at all: it lies inside the look table, or clear of it.
                table = buildprofile.PUBLIC_LOOK_TABLE, buildprofile.PUBLIC_LOOK_TABLE + buildprofile.LOOK_TABLE_BYTES
                if at < table[1] and table[0] < at + size and not (table[0] <= at and at + size <= table[1]):
                    raise ValueError('Region %s %#x+%d crosses the look table edge' % (name, at, size))
                at = buildprofile.translate(at, BODY)
            raw = programs[name][at:at + size]
            if len(raw) != size:
                raise ValueError('Region %s %#x+%d lies outside the program' % (name, at, size))
            rows.append({'offset': at, 'bytes': size, 'zlib_base64': buildprofile.encode(raw)})
        output['programs'][name] = {'bytes': len(programs[name]), 'regions': rows}
    return output


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--components', type=Path, required=True, help='folder holding the body appFw.so and cpapp-b.bin')
    parser.add_argument('--output', type=Path, default=buildprofile.ASSETS / BODY.regions_file)
    args = parser.parse_args(argv)
    ap, cp = ((args.components / name).read_bytes() for name in buildprofile.PROGRAMS)
    output = reference(ap, cp, buildprofile.regions_document(PUBLIC))
    args.output.write_text(json.dumps(output, indent=2) + '\n', encoding='utf-8')
    print({'file': str(args.output), 'bytes': args.output.stat().st_size,
           'regions': {name: len(spec['regions']) for name, spec in output['programs'].items()}, 'camera_io': False})


if __name__ == '__main__':
    main()
