"""Bundled film looks with their source licences and measured fit; no conversion or USB."""
import json
import math
from pathlib import Path
from looktool import lookfile
from .paths import ROOT

SCHEMA = 'a7c2-film-look-library/1'
KINDS = ('negative', 'slide', 'cine', 'style')
REQUIRED = ('id', 'name', 'kind', 'file', 'source', 'modification', 'shareable')
SOURCE = ('project', 'author', 'url', 'licence')
# Held-out fit (8-bit RGB levels) of the accepted paired library bundled with the
# app, 15 colour looks: median MAE 2.39 / P95 8.02; worst accepted (Classic
# Negative) 4.82 / 14.76. A look at or inside the median is good, at or inside the
# worst accepted look is fair, anything beyond it is poor.
GOOD = (2.39, 8.02)
ACCEPTED = (4.82, 14.76)


def location():
    return ROOT / 'desktop-assets/film-looks-v1'


def rating(mae, p95):
    if mae <= GOOD[0] and p95 <= GOOD[1]:
        return 'good'
    if mae <= ACCEPTED[0] and p95 <= ACCEPTED[1]:
        return 'fair'
    return 'poor'


def held_out(document):
    value = document
    for key in ('validation', 'metrics', 'virtual_heldout_validation_replica'):
        value = value.get(key) if isinstance(value, dict) else None
    return value if isinstance(value, dict) else {}


def measurement(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and value >= 0


def document_fit(document):
    metrics = held_out(document)
    mae, p95 = metrics.get('RGB_MAE_8bit'), metrics.get('RGB_P95_8bit')
    if not (measurement(mae) and measurement(p95)):
        return {'rating': 'unknown', 'mae': None, 'p95': None}
    return {'rating': rating(mae, p95), 'mae': mae, 'p95': p95}


def file_fit(path):
    try:
        document = lookfile.read(path)
    except (OSError, ValueError) as exc:
        return {'rating': 'invalid', 'mae': None, 'p95': None, 'error': str(exc)}
    return document_fit(document)


def text(value):
    return isinstance(value, str) and bool(value.strip())


def checked(entry, root):
    if not isinstance(entry, dict) or any(key not in entry for key in REQUIRED):
        raise ValueError('Film look entry is incomplete: %r' % (entry,))
    label = entry['id']
    if not all(text(entry[key]) for key in ('id', 'name', 'file', 'modification')):
        raise ValueError('Film look %r has an empty field' % label)
    source = entry['source']
    if not isinstance(source, dict) or not all(text(source.get(key)) for key in SOURCE):
        raise ValueError('Film look %r has no complete source and licence' % label)
    if not source['url'].startswith('https://'):
        raise ValueError('Film look %r source is not an https address' % label)
    if entry['kind'] not in KINDS:
        raise ValueError('Film look %r has an unknown kind %r' % (label, entry['kind']))
    if not isinstance(entry['shareable'], bool) or not isinstance(entry.get('notes', ''), str):
        raise ValueError('Film look %r has an invalid shareable flag or notes' % label)
    name = entry['file']
    if Path(name).name != name or not name.endswith('.a7look'):
        raise ValueError('Film look %r file must be an .a7look inside the library' % label)
    path = Path(root) / name
    if not path.is_file():
        raise FileNotFoundError('Film look %r file is missing: %s' % (label, path))
    return dict(entry, notes=entry.get('notes', ''), path=path, fit=document_fit(lookfile.read(path)))


def catalog(root=None):
    """Every bundled look, validated; an absent library is empty."""
    root = location() if root is None else Path(root)
    if not root.exists():
        return []
    document = json.loads((root / 'catalog.json').read_text(encoding='utf-8'))
    if not isinstance(document, dict) or document.get('schema') != SCHEMA or not isinstance(document.get('looks'), list):
        raise ValueError('Unknown film look catalog')
    looks, seen = [], set()
    for entry in document['looks']:
        look = checked(entry, root)
        if look['id'] in seen:
            raise ValueError('Duplicate film look id %r' % look['id'])
        seen.add(look['id'])
        looks.append(look)
    return looks
