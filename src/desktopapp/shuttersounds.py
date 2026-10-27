"""Bundled shutter sounds with their licences: ready-made sources for the shutter sound page.
Reads only the catalog and WAV headers; never converts audio or opens a camera."""
import json
from pathlib import Path
import re
import wave
from .paths import ROOT

SCHEMA = 'a7c2-shutter-sounds/1'
REQUIRED = ('id', 'name', 'file', 'source', 'changes', 'credit')
SOURCE = ('title', 'author', 'url', 'licence')
# Licences a public app may bundle, with the wording Freesound's attribution uses. CC BY needs the
# credit and a statement of the changes; nothing NonCommercial or ShareAlike is accepted.
LICENCES = {'CC0 1.0': ('Creative Commons 0', None),
            'CC BY 4.0': ('Attribution 4.0', 'https://creativecommons.org/licenses/by/4.0/')}
SLUG = re.compile(r'[a-z0-9][a-z0-9-]*\Z')
# The clip lengths the shutter sound page accepts (its length field).
SHORTEST, LONGEST = 0.01, 2.0


def location():
    return ROOT / 'desktop-assets/shutter-sounds-v1'


def text(value):
    return isinstance(value, str) and bool(value.strip())


def seconds(path):
    """Length of a PCM WAV in seconds, to the millisecond the page's length field shows."""
    try:
        with wave.open(str(path), 'rb') as clip:
            frames, rate = clip.getnframes(), clip.getframerate()
    except (wave.Error, EOFError) as exc:
        raise ValueError('%s is not a PCM WAV file: %s' % (path, exc)) from exc
    return round(frames / rate, 3)


def checked(entry, root):
    if not isinstance(entry, dict) or any(key not in entry for key in REQUIRED):
        raise ValueError('Shutter sound entry is incomplete: %r' % (entry,))
    label = entry['id']
    if not (text(label) and SLUG.match(label)):
        raise ValueError('Shutter sound id %r is not a lower-case slug' % (label,))
    if not all(text(entry[key]) for key in ('name', 'file', 'credit')) or not isinstance(entry['changes'], str):
        raise ValueError('Shutter sound %r has an empty field' % label)
    source = entry['source']
    if not isinstance(source, dict) or not all(text(source.get(key)) for key in SOURCE):
        raise ValueError('Shutter sound %r has no complete source and licence' % label)
    if not source['url'].startswith('https://'):
        raise ValueError('Shutter sound %r source is not an https address' % label)
    if source['licence'] not in LICENCES:
        raise ValueError('Shutter sound %r has a licence the app cannot bundle: %r' % (label, source['licence']))
    if LICENCES[source['licence']][1] and not text(entry['changes']):
        raise ValueError('Shutter sound %r is %s and must state its changes' % (label, source['licence']))
    if source['author'] not in entry['credit'] or source['url'] not in entry['credit']:
        raise ValueError('Shutter sound %r credit does not name its author and source' % label)
    name = entry['file']
    if Path(name).name != name or not name.endswith('.wav'):
        raise ValueError('Shutter sound %r file must be a .wav inside the library' % label)
    path = Path(root) / name
    if not path.is_file():
        raise FileNotFoundError('Shutter sound %r file is missing: %s' % (label, path))
    length = seconds(path)
    if not SHORTEST <= length <= LONGEST:
        raise ValueError('Shutter sound %r length %.3f s is outside %.2f–%.1f s' % (label, length, SHORTEST, LONGEST))
    return dict(entry, path=path, seconds=length)


def catalog(root=None):
    """Every bundled sound, validated, most loved first; an absent library is empty."""
    root = location() if root is None else Path(root)
    if not root.exists():
        return []
    document = json.loads((root / 'catalog.json').read_text(encoding='utf-8'))
    if not isinstance(document, dict) or document.get('schema') != SCHEMA or not isinstance(document.get('sounds'), list):
        raise ValueError('Unknown shutter sound catalog')
    sounds, seen = [], set()
    for entry in document['sounds']:
        sound = checked(entry, root)
        if sound['id'] in seen:
            raise ValueError('Duplicate shutter sound id %r' % sound['id'])
        seen.add(sound['id'])
        sounds.append(sound)
    return sounds
