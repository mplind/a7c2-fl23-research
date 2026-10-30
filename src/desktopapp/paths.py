import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
# The app icon for the Dock and the window. desktop.spec ships it at this path (and gives the bundle the
# same file), so it resolves in the source tree and in the packaged app; make_icon.py beside it redraws it.
APP_ICON = ROOT / 'dev/desktop/icon/AppIcon.icns'
# The edition a package was built as, which desktop.spec records beside the app's files: public or
# personal. A source tree has none.
EDITION_RECORD = ROOT / 'edition.json'
EDITIONS = ('personal', 'public')


def edition():
    """The edition this package records, or None in a source tree."""
    if not EDITION_RECORD.is_file():
        return None
    value = json.loads(EDITION_RECORD.read_text(encoding='utf-8')).get('edition')
    if value not in EDITIONS:
        raise ValueError('Unknown edition %r in %s' % (value, EDITION_RECORD))
    return value


def data_root():
    explicit = os.environ.get('A7C2_DESKTOP_DATA')
    if explicit:
        return Path(explicit).expanduser().resolve()
    if sys.platform == 'win32':
        return Path(os.environ.get('LOCALAPPDATA', str(Path.home()))) / 'A7C2Tools'
    if sys.platform == 'darwin':
        return Path.home() / 'Library/Application Support/A7C2Tools'
    return Path.home() / '.local/share/a7c2-tools'


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + '.new')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
    temporary.replace(path)


def load_settings():
    path = data_root() / 'desktop.json'
    return json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}


def save_settings(settings):
    write_json(data_root() / 'desktop.json', settings)
