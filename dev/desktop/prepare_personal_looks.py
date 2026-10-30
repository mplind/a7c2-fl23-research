"""Copy the owner's personal film library and his six default looks into the desktop assets.

Usage: python dev/desktop/prepare_personal_looks.py <personal library folder>

The folder is the film-look bake-off's finished library: manifest.json, looks/, samples/, writeups/ and
its guides. Its looks are converted from apps the owner bought (Dehancer, DxO FilmPack) or are
Fujifilm-derived, so they are for his personal use only: both targets sit under desktop-assets/, which
git ignores, and only the personal edition of the build bundles them (assets_check.PERSONAL). Every look
is copied byte for byte and checked against the manifest's sha256; nothing is converted or refitted.
Both targets are checked and staged before either replaces the earlier one.
"""
import argparse
import hashlib
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'src'), str(ROOT / 'src/looks'), str(ROOT / 'dev/desktop')]
from looktool import lookfile, lookpreview  # noqa: E402
from desktopapp import looklibrary, presets  # noqa: E402
import assets_check  # noqa: E402
import prepare_film_looks  # noqa: E402

LIBRARY = ROOT / assets_check.PERSONAL_LIBRARY
PACK = ROOT / assets_check.PERSONAL_PACK
# Beside the looks, so the library's "Licence notices…" button, which shows the folder, reaches them:
# GUIDE.html shows the samples; README.md points to the write-ups and the manifest.
DOCUMENTS = ('README.md', 'GUIDE.html', 'HOW-TO-ADD-A-STOCK.md', 'manifest.json')
FOLDERS = ('samples', 'writeups')
REQUIRED = ('id', 'stock', 'camera_name', 'source', 'source_app', 'sim', 'file', 'sha256', 'default_slot',
            'exposure_comp_thirds', 'why_included', 'licence')
# The library's kind for each film stock, by the manifest's 'stock'. A look the manifest marks sim is a
# digital film simulation, so a style. A new stock needs its kind here.
KINDS = {'Kodachrome': 'slide', 'Velvia': 'slide', 'Fuji Provia': 'slide', 'Portra 400': 'negative',
         'Portra 160 NC': 'negative', 'Portra 160 VC': 'negative', 'CineStill 800T': 'cine'}
# The maker and site of each app a paid look was converted from, by the manifest's 'source'.
PURCHASED = {'dehancer': ('Dehancer', 'https://www.dehancer.com/'),
             'dxo': ('DxO', 'https://www.dxo.com/dxo-filmpack/')}
LICENCE = 'Personal use only — converted from a purchased %s licence; not for distribution'
# The Classic Chrome that A7C II Tools already bundles (its paired profile library). It keeps the licence
# the manifest gives it. Its DCP came from 门萨特里顿 (MTriton), as docs/en/notices.md credits it.
BUNDLED = 'fujifilm-bundled'
BUNDLED_SOURCE = ('门萨特里顿 (MTriton)', 'https://github.com/QAQLeonard/a7c2-fl23-research')
NOTICE = 'Personal use only; not for distribution. Each look keeps the licence listed with it.'


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def manifest(source):
    """The manifest's looks, each with every field this script reads; refuses a library that is not
    marked for personal use only."""
    document = json.loads((source / 'manifest.json').read_text(encoding='utf-8'))
    if document.get('personal_use_only') is not True:
        raise ValueError('Refusing %s: its manifest is not marked personal_use_only' % source)
    looks = document.get('looks')
    if not isinstance(looks, list) or not looks:
        raise ValueError('The manifest in %s lists no looks' % source)
    for look in looks:
        missing = [key for key in REQUIRED if key not in look]
        if missing:
            raise ValueError('Look %r lacks %s in the manifest' % (look.get('id'), ', '.join(missing)))
        if not prepare_film_looks.SLUG.match(look['id']):
            raise ValueError('Unsafe look id %r' % look['id'])
        if not presets.thirds(look['exposure_comp_thirds']):
            raise ValueError('Look %r has an invalid exposure amount %r' % (look['id'], look['exposure_comp_thirds']))
    return looks


def six(looks):
    """The looks the manifest puts in Custom 1–6, in slot order."""
    chosen = [look for look in looks if look['default_slot'] is not None]
    slots = [look['default_slot'] for look in chosen]
    if not (all(type(slot) is int for slot in slots) and sorted(slots) == list(range(1, 7))):
        raise ValueError('The manifest must give Custom 1–6 one look each; it gives %r' % slots)
    return sorted(chosen, key=lambda look: look['default_slot'])


def checked(source, look):
    """(path, document) of a look's file: inside the library, as the manifest's sha256 records it, and
    carrying the name the manifest gives it."""
    path = (source / look['file']).resolve()
    if not path.is_relative_to(source.resolve()):
        raise ValueError('%s is outside the library' % look['file'])
    if sha256(path) != look['sha256']:
        raise ValueError('%s does not match its manifest checksum' % look['file'])
    document = lookfile.read(path)
    if document['name'] != look['camera_name']:
        raise ValueError('%s is named %r, not %r' % (look['file'], document['name'], look['camera_name']))
    return path, document


def kind(look):
    if look['sim']:
        return 'style'
    if look['stock'] not in KINDS:
        raise ValueError('No film kind for the stock %r: add it to KINDS' % look['stock'])
    return KINDS[look['stock']]


def source_of(look):
    """The catalog source of a look: the app it came from, its maker, the maker's site and its licence."""
    if look['source'] == BUNDLED:
        author, url = BUNDLED_SOURCE
        return dict(project=look['source_app'], author=author, url=url, licence=look['licence'])
    if look['source'] not in PURCHASED:
        raise ValueError('Unknown source %r for %s' % (look['source'], look['id']))
    maker, url = PURCHASED[look['source']]
    return dict(project=look['source_app'], author=maker, url=url, licence=LICENCE % maker)


def modification(look, document):
    """One line on how the look was made, from the method its file records."""
    method = document.get('method', '')
    if method.startswith('CUBE-'):
        return ('Rendered through %s from an identity image, made into a CUBE LUT and fitted to the A7C II '
                'look table' % look['source_app'])
    if method.startswith('Lightroom-reference-'):
        return 'Fitted from its DCP profile to the A7C II look table, as A7C II Tools bundles it'
    raise ValueError('%s has an unknown conversion method %r' % (look['id'], method))


def entry(look, document, model):
    """The catalog entry of a look. Its notes are the manifest's reason for including it, then what to do
    if it renders dark."""
    note = presets.exposure_note(((look['camera_name'], look['exposure_comp_thirds']),), 'en')
    result = {'id': look['id'], 'name': look['camera_name'], 'kind': kind(look), 'file': look['id'] + '.a7look',
              'source': source_of(look), 'modification': modification(look, document), 'shareable': False,
              'notes': ' '.join(part for part in (look['why_included'], note) if part)}
    colours = prepare_film_looks.swatches(document, model)
    if colours:
        result['swatches'] = colours
    return result


def staging(target):
    folder = target.with_name(target.name + '.partial')
    shutil.rmtree(folder, ignore_errors=True)
    folder.mkdir(parents=True)
    return folder


def write_json(path, document):
    path.write_text(json.dumps(document, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def stage_library(source, looks, target, model):
    folder, entries = staging(target), []
    for look in looks:
        path, document = checked(source, look)
        shutil.copyfile(path, folder / (look['id'] + '.a7look'))
        entries.append(entry(look, document, model))
    for name in DOCUMENTS:
        shutil.copyfile(source / name, folder / name)
    for name in FOLDERS:
        shutil.copytree(source / name, folder / name)
    write_json(folder / 'catalog.json', {'schema': looklibrary.SCHEMA, 'personal_use_only': True, 'looks': entries})
    looklibrary.catalog(folder)  # the new library must load before it replaces the old one
    return folder, entries


def stage_pack(source, looks, target):
    folder, rows = staging(target), []
    for look in six(looks):
        path, _ = checked(source, look)
        name = 'slot%d.a7look' % look['default_slot']
        shutil.copyfile(path, folder / name)
        rows.append(dict(slot=look['default_slot'], name=look['camera_name'], file=name, library_id=look['id'],
                         sha256=look['sha256'], exposure_comp_thirds=look['exposure_comp_thirds'],
                         licence=source_of(look)['licence']))
    write_json(folder / 'pack.json', {'pack': presets.PERSONAL, 'personal_use_only': True, 'notice': NOTICE,
                                      'looks': rows})
    # As One-click will read it: the pack's description, then each slot file's name and photo stage.
    pack = presets.read(folder / 'pack.json', presets.PERSONAL)
    for slot, name in enumerate(pack.names, 1):
        presets.check_slot(folder / ('slot%d.a7look' % slot), name)
    return folder, rows


def prepare(source, library=LIBRARY, pack=PACK, model=None):
    """Stage the personal library and pack from `source`, check both, then replace the earlier ones.
    Returns (catalog entries, pack rows)."""
    source, library, pack = Path(source), Path(library), Path(pack)
    prepare_film_looks.replaceable(library, 'personal film look library', 'catalog.json')
    prepare_film_looks.replaceable(pack, 'six-look pack', 'pack.json')
    looks = manifest(source)
    six(looks)  # refuse an incomplete or doubled default before copying anything
    staged = []
    try:
        folder, entries = stage_library(source, looks, library, lookpreview.load_model() if model is None else model)
        staged.append(folder)
        folder, rows = stage_pack(source, looks, pack)
        staged.append(folder)
    except BaseException:
        for folder in (library.with_name(library.name + '.partial'), pack.with_name(pack.name + '.partial')):
            shutil.rmtree(folder, ignore_errors=True)
        raise
    prepare_film_looks.replace(staged[0], library, 'personal film look library', 'catalog.json')
    prepare_film_looks.replace(staged[1], pack, 'six-look pack', 'pack.json')
    return entries, rows


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('source', type=Path, help='the personal library folder, with manifest.json')
    entries, rows = prepare(parser.parse_args().source)
    print('Prepared %d film looks in %s and the six-look pack %s (%s)'
          % (len(entries), LIBRARY, PACK, ', '.join(row['name'] for row in rows)))


if __name__ == '__main__':
    main()
