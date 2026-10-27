"""Creative Look recipes for the experimental PC Remote writer. Pure logic; never opens USB.

A Recipe is a base look, the eight Creative Look sliders, an optional white
balance, the WB shift and an optional DRO setting. `plan()` compares it with a
camera snapshot and `apply()` performs the plan through a connected
`camera_runtime.ptpremote.RemoteSession`. Both use the snapshot/session by duck
typing, so importing this module loads no USB code.

Property codes and wire values follow Sony's Camera Control PTP 3 Reference; none
of this has been verified on a real ILCE-7CM2 yet.
"""
import math
from dataclasses import dataclass

# Property codes.
POSITION_KEY = 0xD25A
PICTURE_PROFILE = 0xD23F
CREATIVE_LOOK = 0xD0FA
IMAGE_STYLE = 0xD103  # base look of the Custom Look slot selected in CREATIVE_LOOK
WHITE_BALANCE = 0x5005
COLOR_TEMPERATURE = 0xD20F
WB_SHIFT_AB = 0xD21C
WB_SHIFT_GM = 0xD210
DRO = 0xD201

BASE_LOOKS = {'ST': 0x0001, 'PT': 0x0002, 'NT': 0x0003, 'VV': 0x0004, 'VV2': 0x0005, 'FL': 0x0006,
              'IN': 0x0007, 'SH': 0x0008, 'BW': 0x0009, 'SE': 0x000A, 'FL2': 0x000B, 'FL3': 0x000C}
MONOCHROME_LOOKS = ('BW', 'SE')  # the camera greys out Saturation for these
CUSTOM_SLOTS = range(1, 7)
CUSTOM_LOOK = 0x0100  # Custom Look n is CUSTOM_LOOK | n

WHITE_BALANCE_MODES = {
    'AWB': 0x0002, 'Daylight': 0x0004, 'Tungsten': 0x0006, 'Flash': 0x0007,
    'Fluor. Warm White': 0x8001, 'Fluor. Cool White': 0x8002, 'Fluor. Day White': 0x8003,
    'Fluor. Daylight': 0x8004, 'Cloudy': 0x8010, 'Shade': 0x8011, 'C.Temp': 0x8012,
    'Custom 1': 0x8020, 'Custom 2': 0x8021, 'Custom 3': 0x8022, 'Underwater Auto': 0x8030}
KELVIN_RANGE = (2500, 9900, 100)  # Sony menu range; the camera's reported range is checked when planning
DRO_MODES = {'Off': 0x01, 'Lv1': 0x11, 'Lv2': 0x12, 'Lv3': 0x13, 'Lv4': 0x14, 'Lv5': 0x15, 'Auto': 0x1F}
POSITION_KEY_PC = 0x01

# WB shift (p.455): UINT8, 0x9C = B9.00 .. 0xE4 = A9.00, one step = 0.25. The 0xC0
# centre is derived from those end points; plan() refuses a camera whose
# reported range is not centred there.
WB_SHIFT_CENTRE = 0xC0
WB_SHIFT_LIMIT = 9


@dataclass(frozen=True)
class Slider:
    field: str
    code: int
    label: str
    minimum: int
    maximum: int


# The eight Creative Look sliders in camera order, with Sony's documented ranges.
SLIDERS = (
    Slider('contrast', 0xD0FB, 'Contrast', -9, 9),
    Slider('highlights', 0xD0FC, 'Highlights', -9, 9),
    Slider('shadows', 0xD0FD, 'Shadows', -9, 9),
    Slider('fade', 0xD0FE, 'Fade', 0, 9),
    Slider('saturation', 0xD0FF, 'Saturation', -9, 9),
    Slider('sharpness', 0xD100, 'Sharpness', 0, 9),
    Slider('sharpness_range', 0xD101, 'Sharpness Range', 1, 5),
    Slider('clarity', 0xD102, 'Clarity', 0, 9),
)
_SLIDERS_BY_CODE = {s.code: s for s in SLIDERS}
LABELS = {POSITION_KEY: 'Position Key', PICTURE_PROFILE: 'Picture Profile', CREATIVE_LOOK: 'Creative Look',
          IMAGE_STYLE: 'Custom Look style', WHITE_BALANCE: 'White balance', COLOR_TEMPERATURE: 'Colour temperature',
          WB_SHIFT_AB: 'WB shift A-B', WB_SHIFT_GM: 'WB shift G-M', DRO: 'DRO',
          **{s.code: s.label for s in SLIDERS}}


def _is_int(value):
    return type(value) is int


def wb_shift_wire(shift):
    """Wire value for a WB shift in 0.25 steps: 0xC0 + 4*shift (A and G positive)."""
    if isinstance(shift, bool) or not isinstance(shift, (int, float)) or not math.isfinite(shift):
        raise ValueError('WB shift must be a number, not %r' % (shift,))
    steps = shift * 4
    if steps != int(steps) or abs(shift) > WB_SHIFT_LIMIT:
        raise ValueError('WB shift %r is not a 0.25 step between -9 and +9' % (shift,))
    return WB_SHIFT_CENTRE + int(steps)


def _shift_text(wire, positive, negative):
    shift = (wire - WB_SHIFT_CENTRE) / 4
    return '0' if shift == 0 else '%s%g' % (positive if shift > 0 else negative, abs(shift))


def _reverse(mapping):
    return {value: name for name, value in mapping.items()}


_LOOK_NAMES = _reverse(BASE_LOOKS)
_WB_NAMES = _reverse(WHITE_BALANCE_MODES)
_DRO_NAMES = _reverse(DRO_MODES)


def display_value(code, value):
    """Human-readable text for a wire value of one of the recipe properties."""
    if value is None:
        return '?'
    if code == CREATIVE_LOOK and value & ~0xFF == CUSTOM_LOOK and value & 0xFF in CUSTOM_SLOTS:
        return 'Custom Look %d' % (value & 0xFF)
    named = {CREATIVE_LOOK: _LOOK_NAMES, IMAGE_STYLE: _LOOK_NAMES, WHITE_BALANCE: _WB_NAMES, DRO: _DRO_NAMES,
             POSITION_KEY: {0: 'camera', 1: 'PC Remote'}}.get(code)
    if named is not None:
        return named.get(value, '0x%04X' % value)
    if code == WB_SHIFT_AB:
        return _shift_text(value, 'A', 'B')
    if code == WB_SHIFT_GM:
        return _shift_text(value, 'G', 'M')
    if code == COLOR_TEMPERATURE:
        return '%d K' % value
    if code == PICTURE_PROFILE:
        return 'Off' if value == 0 else 'PP%d' % value
    slider = _SLIDERS_BY_CODE.get(code)
    if slider is not None and slider.minimum < 0 and value:
        return '%+d' % value
    return str(value)


@dataclass(frozen=True)
class Recipe:
    """One look to put on the camera.

    target None selects the base look itself and adjusts it in place (the camera
    keeps adjustments per look); 1-6 stores it in Custom Look slot n. White
    balance is camera-wide, never part of a slot. WB shifts are in 0.25 steps,
    A and G positive. Construction validates against Sony's documented ranges;
    plan() checks the camera's own ranges.
    """
    name: str
    base_look: str
    contrast: int
    highlights: int
    shadows: int
    fade: int
    saturation: int
    sharpness: int
    sharpness_range: int
    clarity: int
    target: object = None
    white_balance: object = None
    kelvin: object = None
    wb_shift_ab: float = 0
    wb_shift_gm: float = 0
    dro: object = None
    source: str = ''
    source_url: object = None
    note: str = ''

    def __post_init__(self):
        if not isinstance(self.name, str) or not self.name.strip():
            raise ValueError('A recipe needs a name')
        if self.base_look not in BASE_LOOKS:
            raise ValueError('Unknown base look %r' % (self.base_look,))
        for slider in SLIDERS:
            value = getattr(self, slider.field)
            if not _is_int(value) or not slider.minimum <= value <= slider.maximum:
                raise ValueError('%s must be an integer from %d to %d, not %r' % (
                    slider.label, slider.minimum, slider.maximum, value))
        if self.target is not None and (not _is_int(self.target) or self.target not in CUSTOM_SLOTS):
            raise ValueError('Target must be None (the base look) or Custom Look slot 1-6, not %r' % (self.target,))
        if self.white_balance is not None and self.white_balance not in WHITE_BALANCE_MODES:
            raise ValueError('Unknown white balance %r' % (self.white_balance,))
        if (self.white_balance == 'C.Temp') != (self.kelvin is not None):
            raise ValueError('A colour temperature is given exactly when white balance is C.Temp')
        if self.kelvin is not None:
            low, high, step = KELVIN_RANGE
            if not _is_int(self.kelvin) or not low <= self.kelvin <= high or (self.kelvin - low) % step:
                raise ValueError('Colour temperature must be %d-%d K in %d K steps, not %r' % (low, high, step, self.kelvin))
        wb_shift_wire(self.wb_shift_ab)
        wb_shift_wire(self.wb_shift_gm)
        if self.dro is not None and self.dro not in DRO_MODES:
            raise ValueError('Unknown DRO setting %r' % (self.dro,))
        if self.source_url is not None and not str(self.source_url).startswith('https://'):
            raise ValueError('Source URL must be https: %r' % (self.source_url,))

    def slider_values(self):
        """((Slider, value), ...) in camera order."""
        return tuple((slider, getattr(self, slider.field)) for slider in SLIDERS)


SONY_SINGAPORE = 'Sony Singapore, "The Film Library" Creative Look recipes'
_COMMUNITY = 'sonyfilmsimulations.com community recipe by José_57 (ILCE-7CM2)'


def _sony_singapore(name, look, sliders, ab, gm):
    return Recipe(name, look, *sliders, wb_shift_ab=ab, wb_shift_gm=gm, source=SONY_SINGAPORE,
                  note='Source gives no white-balance mode; the shift applies to the current mode. '
                       'Source URL not recorded.')


PRESETS = (
    _sony_singapore('Retro Negative', 'FL', (-2, -2, -2, 2, 2, 0, 1, 1), -2, -0.25),
    _sony_singapore('Vintage Chrome', 'FL3', (-2, -2, 0, 1, 0, 4, 3, 1), 4, 1.75),
    _sony_singapore('Vintage Film', 'IN', (-1, -2, -1, 4, -1, 0, 2, 2), 3, 0.25),
    _sony_singapore('Nostalgic Film', 'NT', (3, -3, -6, 5, -3, 0, 1, 2), 1, 2),
    _sony_singapore('Natural Look', 'PT', (1, -3, 1, 1, -1, 0, 1, 0), 1.5, 0),
    _sony_singapore('Golden Film', 'VV', (1, -1, 1, 0, 0, 0, 1, 2), 1.5, 0.5),
    Recipe('Sunny FL Film', 'FL', 3, -9, 6, 0, 1, 0, 1, 0, white_balance='Shade', wb_shift_ab=1, wb_shift_gm=1,
           dro='Auto', source=_COMMUNITY, source_url='https://sonyfilmsimulations.com/recipe/sunny-fl-film-5c6eed6e/',
           note='The page lists the shift as "A1 B1 G1 M0"; read as A1 G1.'),
    Recipe('Flfilm Look Street Walk', 'FL', 1, -9, 6, 0, 1, 0, 1, 0, white_balance='Daylight', wb_shift_ab=1,
           wb_shift_gm=1, dro='Auto', source=_COMMUNITY,
           source_url='https://sonyfilmsimulations.com/recipe/flfilm-look-street-walk-19423bf3/'),
)


def preset(name):
    """The built-in preset with this name (KeyError if none)."""
    for row in PRESETS:
        if row.name == name:
            return row
    raise KeyError(name)


# ---------------------------------------------------------------- planning
@dataclass(frozen=True)
class Write:
    """One planned 0x9205 write. A provisional write was planned before a selector
    change (look or white balance) and is planned again from a fresh read."""
    code: int
    label: str
    value: int
    current: object = None
    provisional: bool = False

    def describe(self):
        target = display_value(self.code, self.value)
        if self.provisional:
            return '%s: %s (checked again after re-reading the camera)' % (self.label, target)
        return '%s: %s -> %s' % (self.label, display_value(self.code, self.current), target)


@dataclass(frozen=True)
class ReRead:
    """Read every descriptor again and re-plan the remaining steps from it."""
    reason: str


@dataclass(frozen=True)
class Problem:
    code: int
    label: str
    reason: str
    blocking: bool = True


@dataclass(frozen=True)
class Plan:
    recipe: Recipe
    steps: tuple       # Write and ReRead, in execution order
    problems: tuple    # Problem; any blocking one stops apply() before it sends anything
    unchanged: tuple   # ((code, value), ...) already correct on the camera
    targets: dict      # {code: value}, the intended end state of every property the recipe manages

    @property
    def writes(self):
        return tuple(step for step in self.steps if isinstance(step, Write))

    @property
    def blockers(self):
        return tuple(problem for problem in self.problems if problem.blocking)

    @property
    def ok(self):
        return not self.blockers


WRITE, UNCHANGED, BLOCKED = 'write', 'unchanged', 'blocked'


def _centred(descriptor):
    low, high = descriptor.minimum, descriptor.maximum
    return isinstance(low, int) and isinstance(high, int) and low + high == 2 * WB_SHIFT_CENTRE and descriptor.step == 1


class _Planner:
    """Builds one Plan. Descriptors are used only through their attributes and refusal()."""

    def __init__(self, recipe, snapshot):
        self.recipe, self.properties, self.advertised = recipe, snapshot.properties, snapshot.advertised
        self.steps, self.problems, self.unchanged, self.targets = [], [], [], {}

    def problem(self, code, reason, blocking=True):
        self.problems.append(Problem(code, LABELS[code], reason, blocking))

    def descriptor(self, code):
        """None unless the camera both advertised the code (0x9202) and described it (0x9209)."""
        return self.properties.get(code) if code in self.advertised else None

    def write(self, code, value, *, provisional=False, named=False):
        desc = self.descriptor(code)
        if desc is None:
            self.problem(code, 'not offered by this camera (missing from its property list)')
            return BLOCKED
        if named and desc.get_set == 1 and value not in desc.settable_values:
            reason = '%s is not offered by this camera' % display_value(code, value)
        else:
            reason = desc.refusal(value, require_enabled=not provisional)
        if reason:
            self.problem(code, reason)
            return BLOCKED
        self.targets[code] = value
        if not provisional and desc.current == value:
            self.unchanged.append((code, value))
            return UNCHANGED
        self.steps.append(Write(code, LABELS[code], value, None if provisional else desc.current, provisional))
        return WRITE

    def picture_profile(self):
        desc = self.properties.get(PICTURE_PROFILE)
        if desc is not None and desc.current != 0:
            self.problem(PICTURE_PROFILE, '%s is on; turn it off on the camera (this tool never changes '
                         'Picture Profile)' % display_value(PICTURE_PROFILE, desc.current))

    def position_key(self):
        if self.descriptor(POSITION_KEY) is None:
            self.problem(POSITION_KEY, 'not offered by this camera; settings follow the camera dials', blocking=False)
        else:
            self.write(POSITION_KEY, POSITION_KEY_PC, named=True)

    def look(self):
        base = BASE_LOOKS[self.recipe.base_look]
        if self.recipe.target is None:
            states = [self.write(CREATIVE_LOOK, base, named=True)]
        else:
            states = [self.write(CREATIVE_LOOK, CUSTOM_LOOK | self.recipe.target, named=True)]
            if states[0] != BLOCKED:
                states.append(self.write(IMAGE_STYLE, base, provisional=states[0] == WRITE, named=True))
        if BLOCKED in states:
            return BLOCKED
        if WRITE in states:
            self.steps.append(ReRead('Creative Look selection changed'))
            return WRITE
        return UNCHANGED

    def sliders(self, provisional):
        for slider, value in self.recipe.slider_values():
            if slider.field == 'saturation' and self.recipe.base_look in MONOCHROME_LOOKS:
                self.problem(slider.code, 'not used by %s; the camera greys it out, so it is left alone'
                             % self.recipe.base_look, blocking=False)
            else:
                self.write(slider.code, value, provisional=provisional)

    def white_balance(self):
        if self.recipe.white_balance is None:
            return UNCHANGED
        state = self.write(WHITE_BALANCE, WHITE_BALANCE_MODES[self.recipe.white_balance], named=True)
        if state == WRITE:
            self.steps.append(ReRead('White balance changed'))
        return state

    def white_balance_details(self, provisional):
        if self.recipe.kelvin is not None:
            self.write(COLOR_TEMPERATURE, self.recipe.kelvin, provisional=provisional)
        for code, shift in ((WB_SHIFT_AB, self.recipe.wb_shift_ab), (WB_SHIFT_GM, self.recipe.wb_shift_gm)):
            desc = self.descriptor(code)
            if desc is not None and not _centred(desc):
                self.problem(code, 'the camera reports range %r..%r step %r; the 0xC0-centred encoding is '
                             'unconfirmed for it' % (desc.minimum, desc.maximum, desc.step))
            else:
                self.write(code, wb_shift_wire(shift), provisional=provisional)

    def dro(self):
        if self.recipe.dro is not None:
            self.write(DRO, DRO_MODES[self.recipe.dro], named=True)


def plan(recipe, snapshot):
    """Ordered writes that turn `snapshot` into `recipe`, plus reasons for anything that cannot be written.

    Order: Position Key, Creative Look (and the slot's style), re-read, the eight
    sliders, white balance, re-read, colour temperature (C.Temp only), WB shifts,
    DRO. Values already on the camera are skipped. Only properties the camera
    advertised are ever planned; Picture Profile is never written.
    """
    planner = _Planner(recipe, snapshot)
    planner.picture_profile()
    planner.position_key()
    look = planner.look()
    if look != BLOCKED:  # sliders belong to the selected look; never adjust the wrong one
        planner.sliders(provisional=look == WRITE)
    white_balance = planner.white_balance()
    if white_balance != BLOCKED:  # shifts are stored per white-balance mode
        planner.white_balance_details(provisional=white_balance == WRITE)
    planner.dro()
    return Plan(recipe, tuple(planner.steps), tuple(planner.problems), tuple(planner.unchanged), dict(planner.targets))


# ---------------------------------------------------------------- applying
# Properties the camera may change by itself when a selector is written.
_SLIDER_CODES = frozenset(s.code for s in SLIDERS)
DEPENDENTS = {CREATIVE_LOOK: _SLIDER_CODES | {IMAGE_STYLE}, IMAGE_STYLE: _SLIDER_CODES,
              WHITE_BALANCE: frozenset({COLOR_TEMPERATURE, WB_SHIFT_AB, WB_SHIFT_GM})}


@dataclass(frozen=True)
class Completed:
    """A write the camera accepted and read back at its target value."""
    write: Write
    before: object
    after: object
    sent: bool  # False when a fresh read already showed the target


@dataclass(frozen=True)
class ApplyResult:
    completed: tuple
    final: object  # the snapshot read after the last write


class ApplyError(RuntimeError):
    """apply() stopped. `completed` lists exactly the verified writes.

    failed/outcome describe the write in flight, if any: 'not_sent', 'rejected'
    (camera refused), 'not_applied' (accepted, never read back) or 'unknown'
    (no reliable answer; the session is unusable and nothing more was sent).
    """

    def __init__(self, message, *, completed=(), failed=None, outcome=None, problems=(), unexpected=(),
                 mismatched=()):
        self.completed, self.failed, self.outcome = tuple(completed), failed, outcome
        self.problems, self.unexpected, self.mismatched = tuple(problems), tuple(unexpected), tuple(mismatched)
        done = ', '.join(row.write.label for row in self.completed) or 'none'
        super().__init__('%s Completed writes: %s.' % (message, done))


def _label(code):
    return LABELS.get(code, '0x%04X' % code)


def _reasons(problems):
    return '; '.join('%s: %s' % (problem.label, problem.reason) for problem in problems)


def changed_settings(before, after):
    """Codes of settings whose value differs between two snapshots.

    Read-only status values (battery, focus indication, ...) and greyed-out
    values, which Sony does not guarantee (p.121), are ignored. A setting that
    appears or disappears counts as changed.
    """
    changed = []
    for code in sorted(set(before.properties) | set(after.properties)):
        old, new = before.properties.get(code), after.properties.get(code)
        if old is None or new is None:
            if (old or new).get_set == 1:
                changed.append(code)
        elif (old.get_set == 1 or new.get_set == 1) and old.enabled and new.enabled and old.current != new.current:
            changed.append(code)
    return changed


def apply(session, planned):
    """Execute a plan the user reviewed, verifying each write and the end state.

    Refuses (sending nothing) when the plan has blockers or the camera no longer
    matches it. Each write goes through session.set_property (fresh read, one
    write, read-back). At a ReRead step the rest is re-planned from a full read.
    Stops at the first failure. Finishes with a full read: every intended value
    must hold, and no other setting may have changed. Raises ApplyError.
    """
    if not planned.ok:
        raise ApplyError('The plan has blockers; nothing was sent: %s.' % _reasons(planned.blockers),
                         problems=planned.blockers)
    completed = []

    def read(context):
        try:
            return session.read_all()
        except Exception as exc:
            raise ApplyError('%s failed: %s.' % (context, exc), completed=completed) from exc

    baseline = read('Reading the camera before writing')
    current = plan(planned.recipe, baseline)
    if not current.ok or current.steps != planned.steps:
        raise ApplyError('The camera settings changed since this plan was made; nothing was sent. Plan again.',
                         problems=current.blockers)
    intended, steps = dict(current.targets), list(current.steps)
    while steps:
        step = steps.pop(0)
        if isinstance(step, ReRead):
            fresh = plan(planned.recipe, read('Re-reading after: %s' % step.reason))
            if not fresh.ok:
                raise ApplyError('%s; the camera now refuses the rest: %s.' % (step.reason, _reasons(fresh.blockers)),
                                 completed=completed, problems=fresh.blockers)
            done = {row.write.code for row in completed}
            reverted = [write.label for write in fresh.writes if write.code in done]
            if reverted:
                raise ApplyError('The camera reverted %s after it was verified.' % ', '.join(reverted),
                                 completed=completed)
            intended.update(fresh.targets)
            steps = list(fresh.steps)
            continue
        try:
            result = session.set_property(step.code, step.value)
        except Exception as exc:
            raise ApplyError('Stopped at %s: %s.' % (step.describe(), exc), completed=completed, failed=step,
                             outcome=getattr(exc, 'outcome', 'unknown')) from exc
        completed.append(Completed(step, result.before.current, result.after.current, result.sent))
    final = read('Final read-back')
    mismatched = tuple((code, value, final.properties[code].current if code in final.properties else None)
                       for code, value in sorted(intended.items())
                       if code not in final.properties or final.properties[code].current != value)
    written = {row.write.code for row in completed}
    allowed = set(intended).union(*(DEPENDENTS.get(code, ()) for code in written))
    unexpected = tuple(code for code in changed_settings(baseline, final) if code not in allowed)
    if mismatched or unexpected:
        details = ['%s reads %s instead of %s' % (_label(code), display_value(code, got), display_value(code, want))
                   for code, want, got in mismatched]
        details += ['unexpected change to %s' % _label(code) for code in unexpected]
        raise ApplyError('Final check failed: %s.' % '; '.join(details), completed=completed,
                         unexpected=unexpected, mismatched=mismatched)
    return ApplyResult(tuple(completed), final)
