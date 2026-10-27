"""Copy the accepted film looks and their licence notices into the desktop assets.

Usage: python dev/desktop/prepare_film_looks.py <looks folder with metrics.json>
Only looks marked kept are copied; their embedded source cubes travel inside the
.a7look files, so the .cube files themselves are not needed.
"""
import argparse
import json
import os
from pathlib import Path
import re
import shutil
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'src'), str(ROOT / 'src/looks')]
from looktool import lookfile, lookpreview  # noqa: E402
from desktopapp import looklibrary  # noqa: E402

TARGET = ROOT / 'desktop-assets/film-looks-v1'
NOTICES = ('LICENSE-NOTICE.txt', 'SPEKTRAFILM_LICENSE.txt', 'CHANGELOG.txt')
SHAREABLE = ('CC BY ', 'CC BY-SA ', 'CC0', 'MIT')
SLUG = re.compile(r'[a-z0-9][a-z0-9-]*\Z')
STEEP = 'Deep blacks and a steep tone curve: check the shadows in the preview.'
# Measured on the shipped fits (looks README): where the camera prediction leaves the source.
CAVEATS = {
    'velvia100': 'The camera fit leaves a slight cyan cast in the deep shadows.',
    'vision3-500t-2383': 'The camera fit renders highlights warmer and brighter than the source.',
}


def modification(look):
    source = look['source']
    bridged = ' through a Sony ST to ACEScct bridge' if look.get('chosen_variant') == 'composed' else ''
    stage = (source.get('process') + '; ') if source.get('process') else ''
    text = '%sbaked to a 33^3 cube%s and fitted to the A7C II look table (see CHANGELOG.txt)' % (stage, bridged)
    return text[0].upper() + text[1:]


def notes(look):
    return ' '.join(part for part in (STEEP if look.get('steep_curve') else '', CAVEATS.get(look['slug'], '')) if part)


def swatches(document, model):
    """The look's predicted in-camera rendering of the reference colours as #RRGGBB, or None for a
    look without fit data (nothing to predict from)."""
    reference = [rgb for _, rgb in looklibrary.REFERENCE]
    try:
        rendered = lookpreview.predict(document, [[channel / 255 for channel in rgb] for rgb in reference], model)
    except ValueError:
        return None
    return ['#%02X%02X%02X' % tuple(int(round(min(max(channel, 0.0), 1.0) * 255)) for channel in rgb)
            for rgb in rendered]


def entry(look, document=None, model=None):
    source = {key: look['source'][key] for key in looklibrary.SOURCE}
    result = {'id': look['slug'], 'name': look['camera_name'], 'kind': look['kind'], 'file': look['slug'] + '.a7look',
              'source': source, 'modification': modification(look),
              'shareable': source['licence'].startswith(SHAREABLE), 'notes': notes(look)}
    colours = swatches(document, model) if document is not None else None
    if colours:
        result['swatches'] = colours
    return result


def replace(staging, target, what='film look library'):
    """Swap a prepared staging folder in for target, which must be an earlier library (it has a catalog)."""
    if target.exists():
        if not (target / 'catalog.json').is_file():
            raise RuntimeError('Refusing to replace %s: it is not a %s' % (target, what))
        shutil.rmtree(target)
    os.replace(staging, target)


def prepare(source, target=TARGET):
    source, target = Path(source), Path(target)
    looks = [look for look in json.loads((source / 'metrics.json').read_text(encoding='utf-8'))['looks'] if look['kept']]
    staging = target.with_name(target.name + '.partial')
    shutil.rmtree(staging, ignore_errors=True)
    staging.mkdir(parents=True)
    entries, model = [], lookpreview.load_model()
    for look in looks:
        if not SLUG.match(look['slug']):
            raise ValueError('Unsafe look slug %r' % look['slug'])
        name = look['slug'] + '.a7look'
        document = lookfile.read(source / name)
        shutil.copyfile(source / name, staging / name)
        entries.append(entry(look, document, model))
    for name in NOTICES:
        shutil.copyfile(source / name, staging / name)
    catalog = {'schema': looklibrary.SCHEMA, 'looks': entries}
    (staging / 'catalog.json').write_text(json.dumps(catalog, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    looklibrary.catalog(staging)  # the new library must load before it replaces the old one
    replace(staging, target)
    return entries


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('source', type=Path)
    entries = prepare(parser.parse_args().source)
    print('Prepared %d film looks in %s' % (len(entries), TARGET))


if __name__ == '__main__':
    main()
