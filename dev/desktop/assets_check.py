"""Distribution assets (git-ignored) that a build must not ship without; checked by desktop.spec."""
from pathlib import Path

PRESETS = 'desktop-assets/presets/default-six-v1'
FILM_LIBRARY = 'desktop-assets/film-looks-v1/catalog.json'


def require(root):
    root = Path(root)
    for slot in range(1, 7):
        path = root / PRESETS / ('slot%d.a7look' % slot)
        if not path.is_file():
            raise FileNotFoundError('Prepare the six-look distribution pack first: ' + str(path))
    path = root / FILM_LIBRARY
    if not path.is_file():
        raise FileNotFoundError('Prepare the film look library first (dev/desktop/prepare_film_looks.py): ' + str(path))
