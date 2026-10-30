"""Distribution assets (git-ignored) that a build must not ship without, and which build edition ships
The owner's personal assets; checked by desktop.spec."""
import os
from pathlib import Path

PRESETS = 'desktop-assets/presets/default-six-v1'
FILM_LIBRARY = 'desktop-assets/film-looks-v1/catalog.json'
SHUTTER_SOUNDS = 'desktop-assets/shutter-sounds-v1/catalog.json'
# The owner's personal assets (git-ignored): his film library and his six default looks, converted from apps
# he bought or Fujifilm-derived, so for his personal use only. Only the personal edition bundles them;
# the public edition, the one any release is built from, leaves them out.
PERSONAL_LIBRARY = 'desktop-assets/film-looks-personal-v1'
PERSONAL_PACK = 'desktop-assets/presets/personal-six-v1'
PERSONAL = (PERSONAL_LIBRARY, PERSONAL_PACK)
EDITIONS = ('personal', 'public')


def inside(relative, folder):
    """Whether the path `relative` lies inside `folder`, both from the repository root."""
    parts, prefix = Path(relative).parts, Path(folder).parts
    return parts[:len(prefix)] == prefix and len(parts) > len(prefix)


def personal(relative):
    """Whether the file at `relative` (from the repository root) belongs to a personal asset."""
    return any(inside(relative, folder) for folder in PERSONAL)


def personal_sample(relative):
    """Whether `relative` is one of the personal library's sample pictures, which its GUIDE.html shows:
    the only .jpg files a build ships."""
    return inside(relative, PERSONAL_LIBRARY + '/samples') and Path(relative).suffix.lower() == '.jpg'


def default_edition(root):
    """The edition build.py makes unless told otherwise: personal where the personal assets are (the owner's
    Mac), else public."""
    return 'personal' if any((Path(root) / folder).exists() for folder in PERSONAL) else 'public'


def edition():
    """The edition desktop.spec builds: A7C2_EDITION, which build.py sets."""
    value = os.environ.get('A7C2_EDITION')
    if value not in EDITIONS:
        raise RuntimeError('Build with dev/desktop/build.py, or set A7C2_EDITION to personal or public '
                           '(it is %r).' % value)
    return value


def require(root, edition):
    if edition not in EDITIONS:
        raise ValueError('Unknown edition %r; it is personal or public.' % edition)
    root = Path(root)
    for slot in range(1, 7):
        path = root / PRESETS / ('slot%d.a7look' % slot)
        if not path.is_file():
            raise FileNotFoundError('Prepare the six-look distribution pack first: ' + str(path))
    path = root / FILM_LIBRARY
    if not path.is_file():
        raise FileNotFoundError('Prepare the film look library first (dev/desktop/prepare_film_looks.py): ' + str(path))
    path = root / SHUTTER_SOUNDS
    if not path.is_file():
        raise FileNotFoundError('Prepare the shutter sounds first (dev/desktop/prepare_shutter_sounds.py): ' + str(path))
    if edition == 'personal':
        for folder, descriptor in ((PERSONAL_LIBRARY, 'catalog.json'), (PERSONAL_PACK, 'pack.json')):
            path = root / folder / descriptor
            if not path.is_file():
                raise FileNotFoundError('Prepare the personal assets first (dev/desktop/prepare_personal_looks.py), '
                                        'or build with --edition public: ' + str(path))
