"""Bundled film looks with their source licences and measured fit; no conversion or USB."""
import json
import math
import re
from pathlib import Path
from looktool import lookfile
from .paths import ROOT

SCHEMA = 'a7c2-film-look-library/1'
KINDS = ('negative', 'slide', 'cine', 'style')
REQUIRED = ('id', 'name', 'kind', 'file', 'source', 'modification', 'shareable')
SOURCE = ('project', 'author', 'url', 'licence')
# Held-out fit (8-bit RGB levels) of the accepted paired library bundled with the
# app, 15 colour looks: median MAE 2.387 / P95 8.023; worst accepted (Classic
# Negative) 4.819 / 14.760. A look at or inside the median is good, at or inside the
# worst accepted look is fair, anything beyond it is poor. Rounded outward, so the
# library's own median rates good and its worst fair; a test checks this against the
# library whenever it is present.
GOOD = (2.39, 8.03)
ACCEPTED = (4.82, 14.76)
# Reference colours for the library's swatches: ColorChecker patches in sRGB (skin, sky, foliage,
# a warm tone) and a neutral ramp. Each look's catalog entry records its predicted in-camera
# rendering of these, so a stock's character shows before any preview. Names are display keys.
REFERENCE = (('深肤色', (115, 82, 68)), ('浅肤色', (194, 150, 130)), ('蓝天', (98, 122, 157)),
             ('树叶', (87, 108, 67)), ('橙黄', (224, 163, 46)), ('暗部灰', (52, 52, 52)),
             ('中灰', (122, 122, 122)), ('亮部灰', (200, 200, 200)))
HEX = re.compile(r'#[0-9A-Fa-f]{6}\Z')
# What reading a look can raise: lookfile.validate trips KeyError, TypeError or
# AttributeError on a malformed embedded profile, besides ValueError and OSError.
READ_ERRORS = (OSError, ValueError, KeyError, TypeError, AttributeError)


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
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return False
    try:
        return math.isfinite(value) and value >= 0
    except OverflowError:  # an integer too large for a float
        return False


def document_fit(document):
    metrics = held_out(document)
    mae, p95 = metrics.get('RGB_MAE_8bit'), metrics.get('RGB_P95_8bit')
    if not (measurement(mae) and measurement(p95)):
        return {'rating': 'unknown', 'mae': None, 'p95': None}
    return {'rating': rating(mae, p95), 'mae': mae, 'p95': p95}


def file_fit(path):
    """document_fit of the file plus whether it can be previewed (it carries the fitted native controls)."""
    try:
        document = lookfile.read(path)
    except READ_ERRORS as exc:
        return {'rating': 'invalid', 'mae': None, 'p95': None, 'error': str(exc) or type(exc).__name__, 'preview': False}
    return dict(document_fit(document), preview=lookfile.native_controls(document) is not None)


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
    swatches = entry.get('swatches')
    if swatches is not None and not (isinstance(swatches, list) and len(swatches) == len(REFERENCE)
                                     and all(isinstance(value, str) and HEX.match(value) for value in swatches)):
        raise ValueError('Film look %r swatches must be %d #RRGGBB colours' % (label, len(REFERENCE)))
    name = entry['file']
    if Path(name).name != name or not name.endswith('.a7look'):
        raise ValueError('Film look %r file must be an .a7look inside the library' % label)
    path = Path(root) / name
    if not path.is_file():
        raise FileNotFoundError('Film look %r file is missing: %s' % (label, path))
    document = lookfile.read(path)
    return dict(entry, notes=entry.get('notes', ''), swatches=swatches, path=path, fit=document_fit(document),
                preview=lookfile.native_controls(document) is not None)


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


CONCERNS = ('poor', 'unknown', 'invalid')


def fit_concerns(looks):
    """The looks (dicts with a path) whose camera fit is poor, unknown or unreadable, each with its fit."""
    concerns = []
    for look in looks:
        fit = file_fit(look['path'])
        if fit['rating'] in CONCERNS:
            concerns.append(dict(look, fit=fit))
    return concerns
