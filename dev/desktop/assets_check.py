"""Distribution assets (git-ignored) that a build must not ship without, the asset folders each build
edition ships, and the check that a built public package holds none of the owner's personal assets; used
by desktop.spec and build.py."""
import json
import os
from pathlib import Path

PRESETS = 'desktop-assets/presets/default-six-v1'
FILM_LIBRARY = 'desktop-assets/film-looks-v1/catalog.json'
SHUTTER_SOUNDS = 'desktop-assets/shutter-sounds-v1/catalog.json'
# The owner's personal assets (git-ignored, personal use only): a film library and six default looks. All
# of them live under one root, so no public asset folder ever holds one. Only the personal edition ships
# that root; the public edition, the one any release is built from, never does.
PERSONAL_ROOT = 'desktop-assets/personal'
PERSONAL_LIBRARY = PERSONAL_ROOT + '/film-looks-v1'
PERSONAL_PACK = PERSONAL_ROOT + '/presets/personal-six-v1'
PERSONAL = (PERSONAL_LIBRARY, PERSONAL_PACK)
# The desktop-assets folders the public edition ships. Any other folder under desktop-assets/ (a staging
# copy, a Finder copy, an old layout) is left out and named in the build output. desktop.spec ships the
# paired profile library, desktop-assets/profile-library-v1, on its own, through profilepack.
PUBLIC_ASSETS = ('desktop-assets/exiftool', 'desktop-assets/film-looks-v1', PRESETS,
                 'desktop-assets/shutter-sounds-v1', 'desktop-assets/windows')
EDITIONS = ('personal', 'public')


def inside(relative, folder):
    """Whether the path `relative` lies inside `folder`, both from the repository root."""
    parts, prefix = Path(relative).parts, Path(folder).parts
    return parts[:len(prefix)] == prefix and len(parts) > len(prefix)


def personal(relative):
    """Whether the file at `relative` (from the repository root) lies under the personal root."""
    return inside(relative, PERSONAL_ROOT)


def personal_sample(relative):
    """Whether `relative` is one of the personal library's sample pictures, which its GUIDE.html shows:
    the only .jpg files a build ships."""
    return inside(relative, PERSONAL_LIBRARY + '/samples') and Path(relative).suffix.lower() == '.jpg'


def shipped(edition):
    """The desktop-assets folders `edition` ships: the public ones, and for the personal edition the
    personal root."""
    return PUBLIC_ASSETS + ((PERSONAL_ROOT,) if edition == 'personal' else ())


def bundled(relative, edition):
    """Whether the desktop-assets file at `relative` ships in `edition`: only inside a folder it ships."""
    return any(inside(relative, folder) for folder in shipped(edition))


def unlisted(relative, edition):
    """What to name for a desktop-assets file that `edition` leaves out: the shortest leading part of its
    path that is neither a folder `edition` ships nor a folder holding one."""
    parts = Path(relative).parts
    for length in range(2, len(parts) + 1):
        prefix = Path(*parts[:length]).as_posix()
        if not any(folder == prefix or inside(folder, prefix) for folder in shipped(edition)):
            return prefix
    return Path(relative).as_posix()


def default_edition(root):
    """The edition build.py makes unless told otherwise: personal where the personal root is (the owner's
    Mac), else public."""
    return 'personal' if (Path(root) / PERSONAL_ROOT).exists() else 'public'


def edition():
    """The edition desktop.spec builds: A7C2_EDITION, which build.py sets."""
    value = os.environ.get('A7C2_EDITION')
    if value not in EDITIONS:
        raise RuntimeError('Build with dev/desktop/build.py, or set A7C2_EDITION to personal or public '
                           '(it is %r).' % value)
    return value


def required(edition):
    """(path, what to do when it is missing) for each file a build of `edition` must not ship without."""
    if edition not in EDITIONS:
        raise ValueError('Unknown edition %r; it is personal or public.' % edition)
    files = [(PRESETS + '/slot%d.a7look' % slot, 'Prepare the six-look distribution pack first: ')
             for slot in range(1, 7)]
    files += [(FILM_LIBRARY, 'Prepare the film look library first (dev/desktop/prepare_film_looks.py): '),
              (SHUTTER_SOUNDS, 'Prepare the shutter sounds first (dev/desktop/prepare_shutter_sounds.py): ')]
    if edition == 'personal':
        personal = ('Prepare the personal assets first (dev/desktop/prepare_personal_looks.py), '
                    'or build with --edition public: ')
        files += [(PERSONAL_LIBRARY + '/catalog.json', personal), (PERSONAL_PACK + '/pack.json', personal)]
    return files


def require(root, edition):
    for relative, advice in required(edition):
        path = Path(root) / relative
        if not path.is_file():
            raise FileNotFoundError(advice + str(path))


def marked_personal(path):
    """Whether the JSON file at `path` declares itself personal: personal_use_only, or the personal pack's
    own description."""
    try:
        document = json.loads(Path(path).read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return False
    return isinstance(document, dict) and bool(
        document.get('personal_use_only') or document.get('pack') == Path(PERSONAL_PACK).name)


def personal_findings(folder):
    """What in the built package at `folder` is personal, as paths from `folder`: each personal root (a
    desktop-assets/personal folder, wherever the package put it) and each JSON file marked personal
    elsewhere. Empty for a clean public package. Links are listed, never followed."""
    folder, found = Path(folder), []
    prefix = Path(PERSONAL_ROOT).parts
    for current, folders, files in os.walk(folder):
        here = Path(current)
        for name in sorted(folders):
            relative = (here / name).relative_to(folder)
            if relative.parts[-len(prefix):] == prefix:
                found.append(relative.as_posix())
        folders[:] = sorted(name for name in folders
                            if (here / name).relative_to(folder).parts[-len(prefix):] != prefix)
        for name in sorted(files):
            if name.endswith('.json') and marked_personal(here / name):
                found.append((here / name).relative_to(folder).as_posix())
    return found
