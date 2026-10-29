"""Build generic original bytes for project-owned regions, never body backups."""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'src'), str(ROOT / 'src/looks'), str(ROOT / 'src/shutter_sound')]
from desktopapp.worker import setup_runtime
setup_runtime()
from looktool import buildprofile, checkpointworker, device_layout, photoio, photobuild, six
from looktool.devicesession import modules


def merged(spans):
    result = []
    for start, size in sorted(spans):
        end = start + size
        if result and start <= result[-1][1]:
            result[-1][1] = max(end, result[-1][1])
        else:
            result.append([start, end])
    return [(start, end - start) for start, end in result]


def program_spans(programs, legacy_fixtures=None):
    """{'appFw.so': [(offset, size), …], 'cpapp-b.bin': […]}: every tool-owned span of the public
    programs `programs` ({name: bytes}), merged in file order. `legacy_fixtures`, an index of older
    tool outputs, adds every span where those differ from `programs`."""
    regions = {name: [] for name in programs}
    patches = json.loads((ROOT / 'src/camera_runtime/assets/patches.json').read_text(encoding='utf-8'))
    for name, spec in zip(programs, patches):
        regions[name].extend((int(w['file_offset'], 16), len(bytes.fromhex(w['before_hex']))) for w in spec['writes'])
    runtime = device_layout.runtime()
    for spec in runtime['ap_sources']:
        regions['appFw.so'].extend((w['offset'], len(bytes.fromhex(w['hex']))) for w in spec['restore'])
    regions['appFw.so'].extend((0x59896f0 + slot * 0xb8, 4) for slot in range(6))
    for spec in runtime['cp_sources']:
        regions['cpapp-b.bin'].extend((w['offset'], len(bytes.fromhex(w['before']))) for w in spec['windows'])
    regions['cpapp-b.bin'] += [(six.TABLE_FILE, 32 + 6 * six.TABLE_BYTES),
        (photobuild.TABLE_FILE, 0xb27f0e - photobuild.TABLE_FILE), (photobuild.DATA_FILE, 1216)]
    import candidate
    regions['cpapp-b.bin'].extend((at, len(old)) for at, old, _ in candidate.WINDOWS)
    regions['cpapp-b.bin'].extend((w['offset'], len(bytes.fromhex(w['before']))) for w in photoio.template()['hooks'])
    # Derive every reader/path/call edit from the actual sound implementation. This reference is
    # the public build's; build_body_reference.py derives the body build's from it.
    import boot_sound
    public = buildprofile.by_key('public-2.01')
    regions['appFw.so'].extend((at, len(old)) for at, old, new in boot_sound.windows(programs['appFw.so'], build=public))
    sys.path.insert(0,str(ROOT/'src/vertical'))
    from verticaltool import portraitlayout
    regions['appFw.so'].extend((at, len(raw)) for at, raw in portraitlayout.stock_windows())
    if legacy_fixtures:
        index = json.loads(legacy_fixtures.read_text(encoding='utf-8'))
        for key, name in (('three_ap', 'appFw.so'), ('six_ap', 'appFw.so'),
                          ('three_cp', 'cpapp-b.bin'), ('v4_cp', 'cpapp-b.bin')):
            candidate = Path(index[key]).read_bytes()
            regions[name].extend((at, len(old)) for at, old, new in checkpointworker.differences(programs[name], candidate))
    return {name: merged(spans) for name, spans in regions.items()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--components', type=Path, required=True)
    parser.add_argument('--legacy-fixtures', type=Path)
    parser.add_argument('--output', type=Path, default=ROOT / 'src/looks/assets/factory-regions-2.01.json')
    args = parser.parse_args()
    programs = {name: (args.components / name).read_bytes() for name in ('appFw.so', 'cpapp-b.bin')}
    regions = program_spans(programs, args.legacy_fixtures)
    output = {'schema': 'a7c2-factory-regions/1', 'model': 'ILCE-7CM2', 'version': '2.01',
              'source': 'Sony ILCE-7CM2 2.01 official FDAT, model 0x20030014',
              'scope': 'Only supported project program regions and FL23 color-unit subranges; not full firmware or body calibration',
              'programs': {}, 'color_units': {}}
    for name, spans in regions.items():
        rows = []
        for at, size in spans:
            raw = programs[name][at:at + size]
            if len(raw) != size:
                raise ValueError('Reference region outside original file')
            rows.append({'offset': at, 'bytes': size, 'zlib_base64': buildprofile.encode(raw)})
        output['programs'][name] = {'bytes': len(programs[name]), 'regions': rows}
    from looktool.direct import color_regions
    records = modules()[1].backup_records((args.components / 'CX89700_ALLLANG.bin').read_bytes())
    for key, spans in color_regions().items():
        output['color_units'][str(key)] = [{'offset': at, 'bytes': size,
            'zlib_base64': buildprofile.encode(records[1][key].data[at:at + size])} for at, size in spans]
    args.output.write_text(json.dumps(output, indent=2) + '\n', encoding='utf-8')
    print({'file': str(args.output), 'bytes': args.output.stat().st_size,
           'regions': {n: len(v['regions']) for n, v in output['programs'].items()}, 'camera_io': False})


if __name__ == '__main__':
    main()
