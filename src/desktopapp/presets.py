"""Bundled six-look selections, resolved before opening a device.

Two packs exist. The public pack, default-six-v1, comes with every build; the release archive supplies
its slot files without a pack.json (dev/desktop/prepare_assets.py), so its names and its one-click line
are stated here, as they always were. The owner's personal pack, personal-six-v1, lives under the personal
root and ships only in the personal edition (dev/desktop/assets_check.PERSONAL_ROOT); its pack.json names
its six. One-click installs the personal pack when its pack.json is present, else the public pack.

The actual A7Look/DCP assets are distribution attachments, not MIT source.
No fitting or downloading occurs during installation.
"""
import copy
from dataclasses import dataclass
import json
from pathlib import Path

from .i18n import translate
from .paths import ROOT

PACK = 'default-six-v1'
NAMES = ('Classic Neg.', 'Classic Chrome', 'Nostalgic Neg.', 'Astia',
         'GR Positive Film', 'GR Negative Film')
SUMMARY = '1 NC · 2 CC · 3 NN · 4 Astia · 5 GR 正片 · 6 GR 负片'
PERSONAL = 'personal-six-v1'
# Where each pack's slot files are, from the root of the app.
FOLDERS = {PACK: 'desktop-assets/presets/' + PACK, PERSONAL: 'desktop-assets/personal/presets/' + PERSONAL}
# The one-click line naming six looks, filled with their names in slot order.
IN_ORDER = '%s（依次装入自订 1–6）'
# The refusals of a pack that is missing a file or describes something else, filled with the file.
MISSING = '内置六款外观文件缺失，请使用完整工具包；尚未连接相机：%s'
INVALID = '内置六款外观包描述无效，请使用完整工具包；尚未连接相机：%s'
# What to do for looks that render dark: their names, then the amount twice (how dark, how much to add).
ONE_DARK = '%s 画面约暗 %s 档，曝光补偿 +%s EV。'
SEVERAL_DARK = '%s 画面均约暗 %s 档，曝光补偿均 +%s EV。'


@dataclass(frozen=True)
class Pack:
    id: str
    names: tuple       # the look name each slot file carries, Custom 1–6 in order
    dark: tuple = ()   # (name, thirds of a stop) for each look that renders dark, in slot order


def folder(pack):
    """The folder of the slot files of the pack named `pack`."""
    return ROOT / FOLDERS[pack]


def active():
    """The id of the pack One-click installs: the personal pack when its pack.json is present, else the
    public pack."""
    return PERSONAL if (folder(PERSONAL) / 'pack.json').is_file() else PACK


def thirds(value):
    """Whether `value` is an exposure amount in thirds of a stop: a whole number, zero or more."""
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def described(document, pack):
    """The six rows of a pack.json `document` for pack `pack`, or None when it describes anything else:
    Custom 1–6 in order, each with its slot file, its look name and its exposure amount."""
    if not isinstance(document, dict) or document.get('pack') != pack:
        return None
    rows = document.get('looks')
    if not isinstance(rows, list) or len(rows) != 6:
        return None
    for slot, row in enumerate(rows, 1):
        if not (isinstance(row, dict) and row.get('slot') == slot and row.get('file') == 'slot%d.a7look' % slot
                and isinstance(row.get('name'), str) and row['name'].strip()
                and thirds(row.get('exposure_comp_thirds'))):
            return None
    return rows


def read(path, pack):
    """The Pack that the pack.json at `path` describes for pack `pack`; ValueError naming the file when it
    is missing or describes anything else."""
    path = Path(path)
    if not path.is_file():
        raise ValueError(MISSING % path)
    try:
        rows = described(json.loads(path.read_text(encoding='utf-8')), pack)
    except ValueError:  # not JSON, or not UTF-8
        rows = None
    if rows is None:
        raise ValueError(INVALID % path)
    return Pack(pack, tuple(row['name'] for row in rows),
                tuple((row['name'], row['exposure_comp_thirds']) for row in rows if row['exposure_comp_thirds']))


def load(pack):
    """The Pack named `pack`: the public pack from its constants, the personal pack from its pack.json."""
    if pack == PACK:
        return Pack(PACK, NAMES)
    if pack != PERSONAL:
        raise ValueError('Unknown built-in look pack: ' + str(pack))
    return read(folder(pack) / 'pack.json', pack)


def catalog(pack):
    """The slot files of the pack named `pack`, Custom 1–6 in order, without opening them."""
    found = load(pack)
    return [dict(slot=slot, path=str(folder(found.id) / ('slot%d.a7look' % slot)), name=name)
            for slot, name in enumerate(found.names, 1)]


def check_slot(path, name):
    """Refuse a slot file that is missing, unreadable, not named `name` or without its photo stage."""
    from looktool import lookfile
    path = Path(path)
    if not path.is_file():
        raise ValueError(MISSING % path)
    doc = lookfile.read(path)
    lookfile.writer_document(doc)
    if doc['name'] != name or not doc.get('native_photo'):
        raise ValueError('内置外观名称／照片阶段不符：' + str(path))


def resolve(options):
    """Expand an explicit pack choice; ordinary selected-slot jobs stay intact."""
    options = copy.deepcopy(options)
    pack = options.get('preset_pack')
    if not pack:
        return options
    rows = catalog(pack)
    if options.get('looks'):
        raise ValueError('Choose the built-in six looks or custom files, not both')
    for row in rows:
        check_slot(row['path'], row['name'])
    options['looks'] = rows
    return options


def summary(pack, language):
    """The one-click line naming the six looks of `pack`, in `language`: the public pack's own line, as
    before, or a pack.json pack's names in slot order."""
    if pack.id == PACK:
        return translate(SUMMARY, language)
    return in_order(pack.names, language)


def in_order(names, language):
    """The one-click line naming `names`, the looks for Custom 1–6 in slot order, in `language`."""
    return translate(IN_ORDER, language) % translate('、', language).join(names)


def stops(amount):
    """`amount` thirds of a stop as written: ⅓, ⅔, 1, 1⅓ and so on."""
    whole, part = divmod(amount, 3)
    return (str(whole) if whole else '') + ('', '⅓', '⅔')[part]


def exposure_note(dark, language):
    """What to do for the looks in `dark` ((name, thirds) pairs), in `language`: one line for each amount,
    naming its looks in the order given; '' when none renders dark (an amount of 0 needs no line)."""
    groups = {}
    for name, amount in dark:
        if amount:
            groups.setdefault(amount, []).append(name)
    lines = []
    for amount, names in groups.items():
        line = translate(ONE_DARK, language) if len(names) == 1 else translate(SEVERAL_DARK, language)
        lines.append(line % (translate('、', language).join(names), stops(amount), stops(amount)))
    return '\n'.join(lines)
