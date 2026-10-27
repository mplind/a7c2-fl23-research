"""Copy the curated shutter sounds into the desktop assets with their catalog and credits.

Usage: python dev/desktop/prepare_shutter_sounds.py <folder with sources.json and the WAV clips>
sources.json lists the clips most loved first, each with its Freesound title, author, address,
licence and the changes made. The credit lines in the catalog and CREDITS.txt are built from it.
"""
import argparse
import json
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'src'), str(ROOT / 'dev/desktop')]
from desktopapp import shuttersounds  # noqa: E402
from prepare_film_looks import replace  # noqa: E402

SOURCES = 'a7c2-shutter-sound-sources/1'
TARGET = ROOT / 'desktop-assets/shutter-sounds-v1'
FIELDS = ('id', 'name', 'file', 'title', 'author', 'url', 'licence', 'changes')
HEADER = '''SHUTTER SOUND CREDITS

These recordings come from freesound.org. Each was cut to a single shutter
release for the A7C II's electronic shutter sound. They are not covered by
the licence of this program's code: each keeps its own licence, listed below
with its author, source and the changes made.

'''


def credit(sound):
    label, address = shuttersounds.LICENCES[sound['licence']]
    text = '%s by %s -- %s -- License: %s' % (sound['title'], sound['author'], sound['url'], label)
    if address:
        text += ' (%s)' % address
    if sound['changes']:
        text += '. Changes: ' + sound['changes']
    return text


def entry(sound):
    return {'id': sound['id'], 'name': sound['name'], 'file': sound['id'] + '.wav',
            'source': {key: sound[key] for key in shuttersounds.SOURCE},
            'changes': sound['changes'], 'credit': credit(sound)}


def prepare(source, target=TARGET):
    source, target = Path(source), Path(target)
    document = json.loads((source / 'sources.json').read_text(encoding='utf-8'))
    if document.get('schema') != SOURCES:
        raise ValueError('Unknown shutter sound sources file')
    staging = target.with_name(target.name + '.partial')
    shutil.rmtree(staging, ignore_errors=True)
    staging.mkdir(parents=True)
    try:
        entries = []
        for sound in document['sounds']:
            if any(key not in sound for key in FIELDS):
                raise ValueError('Shutter sound source is incomplete: %r' % (sound,))
            if not shuttersounds.SLUG.match(sound['id']) or Path(sound['file']).name != sound['file']:
                raise ValueError('Unsafe shutter sound id or file name: %r' % (sound,))
            if sound['licence'] not in shuttersounds.LICENCES:
                raise ValueError('Shutter sound %r has a licence the app cannot bundle' % sound['id'])
            shutil.copyfile(source / sound['file'], staging / (sound['id'] + '.wav'))
            entries.append(entry(sound))
        (staging / 'catalog.json').write_text(
            json.dumps({'schema': shuttersounds.SCHEMA, 'sounds': entries}, ensure_ascii=False, indent=2) + '\n',
            encoding='utf-8')
        (staging / 'CREDITS.txt').write_text(
            HEADER + ''.join('%s\n  %s\n\n' % (item['name'], item['credit']) for item in entries), encoding='utf-8')
        shuttersounds.catalog(staging)  # the new library must load before it replaces the old one
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    replace(staging, target, 'shutter sound library')
    return entries


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('source', type=Path)
    entries = prepare(parser.parse_args().source)
    print('Prepared %d shutter sounds in %s' % (len(entries), TARGET))


if __name__ == '__main__':
    main()
