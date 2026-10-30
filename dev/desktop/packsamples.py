"""Six-look pack fixtures for desktop tests: the owner's six, stand-in look names, the English line that
names a pack.json pack's six, and a pack.json writer. No camera access."""
import json

from desktopapp import presets

# The owner's six, Custom 1–6, in the order chosen on 29 Oct 2026.
OWNER_SIX = ('Portra 400 (Dehancer)', 'Classic Chrome', 'Kodachrome 64 (Dehancer)', 'Velvia 50 (Dehancer)',
             'CineStill 800T (Dehancer)', 'Portra 160 NC (DxO)')
# Stand-in names for a pack.json pack the tests write.
NAMES = ('Look One', 'Look Two', 'Look Three', 'Look Four', 'Look Five', 'Look Six')
# The English of presets.IN_ORDER: the one-click line naming a pack.json pack's six.
IN_ORDER = ('%s, in Custom 1–6 in that order. They replace what is there now, settings included. '
            'The camera’s own Creative Looks stay.')


def pack_rows(names=NAMES, thirds=(0,) * 6):
    """The six rows of a pack.json: Custom 1–6, each with its slot file, look name and exposure amount."""
    return [dict(slot=slot, name=name, file='slot%d.a7look' % slot, exposure_comp_thirds=dark)
            for slot, (name, dark) in enumerate(zip(names, thirds), 1)]


def write_pack(folder, document=None, **change):
    """A personal pack.json in `folder`: six rows of NAMES unless `document` (a dict or raw text) or
    `change` says otherwise."""
    if document is None:
        document = dict(dict(pack=presets.PERSONAL, personal_use_only=True, notice='Personal use only.',
                             looks=pack_rows()), **change)
    folder.mkdir(parents=True, exist_ok=True)
    (folder / 'pack.json').write_text(document if isinstance(document, str) else json.dumps(document),
                                      encoding='utf-8')
    return folder
