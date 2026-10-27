"""Creative Look recipe model, presets, planning and verified application. Never opens USB.

The camera is test_ptpremote's FakeCamera driven by a small body model: Creative
Look sliders are stored per look/slot, WB shifts per white-balance mode, and
BW/SE grey out Saturation, as the PTP 3 Reference describes.
"""
import dataclasses
import unittest

from desktopapp import recipes
from test_ptpremote import FakeCamera, FakeProp, connected


class WbShiftTests(unittest.TestCase):
    def test_wire_value_is_centre_plus_four_per_step(self):
        cases = {4: 0xD0, -2: 0xB8, 1.75: 0xC7, -0.25: 0xBF, 0: 0xC0, 9: 0xE4, -9: 0x9C, 1.5: 0xC6}
        for shift, wire in cases.items():
            with self.subTest(shift):
                self.assertEqual(recipes.wb_shift_wire(shift), wire)

    def test_invalid_shifts_are_rejected(self):
        for shift in (0.1, 9.25, -9.25, True, 'A1', float('nan'), float('inf'), None):
            with self.subTest(shift), self.assertRaises(ValueError):
                recipes.wb_shift_wire(shift)

    def test_display_of_wire_values(self):
        self.assertEqual(recipes.display_value(recipes.WB_SHIFT_AB, 0xD0), 'A4')
        self.assertEqual(recipes.display_value(recipes.WB_SHIFT_AB, 0xB8), 'B2')
        self.assertEqual(recipes.display_value(recipes.WB_SHIFT_GM, 0xC7), 'G1.75')
        self.assertEqual(recipes.display_value(recipes.WB_SHIFT_GM, 0xBF), 'M0.25')
        self.assertEqual(recipes.display_value(recipes.WB_SHIFT_GM, 0xC0), '0')
        self.assertEqual(recipes.display_value(recipes.CREATIVE_LOOK, 0x000C), 'FL3')
        self.assertEqual(recipes.display_value(recipes.CREATIVE_LOOK, 0x0103), 'Custom Look 3')
        self.assertEqual(recipes.display_value(recipes.WHITE_BALANCE, 0x8011), 'Shade')
        self.assertEqual(recipes.display_value(recipes.COLOR_TEMPERATURE, 5600), '5600 K')
        self.assertEqual(recipes.display_value(recipes.DRO, 0x1F), 'Auto')
        self.assertEqual(recipes.display_value(recipes.PICTURE_PROFILE, 3), 'PP3')
        self.assertEqual(recipes.display_value(0xD0FB, -2), '-2')
        self.assertEqual(recipes.display_value(0xD0FB, 3), '+3')
        self.assertEqual(recipes.display_value(0xD101, 3), '3')
        self.assertEqual(recipes.display_value(recipes.CREATIVE_LOOK, 0x0042), '0x0042')
        self.assertEqual(recipes.display_value(0xD0FB, None), '?')


def fl(**changes):
    values = dict(name='Test', base_look='FL', contrast=0, highlights=0, shadows=0, fade=0, saturation=0,
                  sharpness=0, sharpness_range=1, clarity=0)
    values.update(changes)
    return recipes.Recipe(**values)


class RecipeTests(unittest.TestCase):
    def test_documented_slider_ranges(self):
        self.assertEqual([(s.field, s.code, s.minimum, s.maximum) for s in recipes.SLIDERS], [
            ('contrast', 0xD0FB, -9, 9), ('highlights', 0xD0FC, -9, 9), ('shadows', 0xD0FD, -9, 9),
            ('fade', 0xD0FE, 0, 9), ('saturation', 0xD0FF, -9, 9), ('sharpness', 0xD100, 0, 9),
            ('sharpness_range', 0xD101, 1, 5), ('clarity', 0xD102, 0, 9)])

    def test_valid_recipe(self):
        recipe = fl(target=3, white_balance='C.Temp', kelvin=5600, wb_shift_ab=-1.25, wb_shift_gm=0.5, dro='Lv2')
        self.assertEqual(recipe.target, 3)

    def test_invalid_recipes_are_rejected(self):
        cases = {
            'unknown base look': dict(base_look='XX'),
            'contrast above range': dict(contrast=10),
            'fade below range': dict(fade=-1),
            'sharpness range zero': dict(sharpness_range=0),
            'clarity above range': dict(clarity=10),
            'boolean slider': dict(contrast=True),
            'float slider': dict(contrast=1.0),
            'slot zero': dict(target=0),
            'slot seven': dict(target=7),
            'kelvin without C.Temp': dict(white_balance='Daylight', kelvin=5600),
            'C.Temp without kelvin': dict(white_balance='C.Temp'),
            'kelvin off step': dict(white_balance='C.Temp', kelvin=5550),
            'kelvin out of range': dict(white_balance='C.Temp', kelvin=10000),
            'unknown white balance': dict(white_balance='Sunny'),
            'shift off grid': dict(wb_shift_ab=0.3),
            'shift beyond 9': dict(wb_shift_gm=-9.5),
            'unknown DRO': dict(dro='Lv6'),
            'empty name': dict(name=''),
            'insecure source URL': dict(source_url='http://example.com'),
        }
        for name, change in cases.items():
            with self.subTest(name), self.assertRaises(ValueError):
                fl(**change)

    def test_target_is_chosen_without_changing_the_look(self):
        preset = recipes.preset('Retro Negative')
        slotted = dataclasses.replace(preset, target=2)
        self.assertEqual((slotted.target, slotted.contrast, preset.target), (2, preset.contrast, None))


class PresetTests(unittest.TestCase):
    EXPECTED = {
        # name: (look, 8 sliders, A-B wire, G-M wire, WB, DRO)
        'Retro Negative': ('FL', (-2, -2, -2, 2, 2, 0, 1, 1), 0xB8, 0xBF, None, None),
        'Vintage Chrome': ('FL3', (-2, -2, 0, 1, 0, 4, 3, 1), 0xD0, 0xC7, None, None),
        'Vintage Film': ('IN', (-1, -2, -1, 4, -1, 0, 2, 2), 0xCC, 0xC1, None, None),
        'Nostalgic Film': ('NT', (3, -3, -6, 5, -3, 0, 1, 2), 0xC4, 0xC8, None, None),
        'Natural Look': ('PT', (1, -3, 1, 1, -1, 0, 1, 0), 0xC6, 0xC0, None, None),
        'Golden Film': ('VV', (1, -1, 1, 0, 0, 0, 1, 2), 0xC6, 0xC2, None, None),
        'Sunny FL Film': ('FL', (3, -9, 6, 0, 1, 0, 1, 0), 0xC4, 0xC4, 'Shade', 'Auto'),
        'Flfilm Look Street Walk': ('FL', (1, -9, 6, 0, 1, 0, 1, 0), 0xC4, 0xC4, 'Daylight', 'Auto'),
    }

    def test_every_preset_has_the_published_values(self):
        self.assertEqual([p.name for p in recipes.PRESETS], list(self.EXPECTED))
        for preset in recipes.PRESETS:
            look, sliders, ab, gm, wb, dro = self.EXPECTED[preset.name]
            with self.subTest(preset.name):
                self.assertEqual(preset.base_look, look)
                self.assertEqual(tuple(value for _, value in preset.slider_values()), sliders)
                self.assertEqual((recipes.wb_shift_wire(preset.wb_shift_ab), recipes.wb_shift_wire(preset.wb_shift_gm)), (ab, gm))
                self.assertEqual((preset.white_balance, preset.dro, preset.target, preset.kelvin), (wb, dro, None, None))

    def test_every_preset_carries_its_source(self):
        for preset in recipes.PRESETS:
            with self.subTest(preset.name):
                self.assertTrue(preset.source)
        community = [p for p in recipes.PRESETS if 'sonyfilmsimulations.com' in p.source]
        self.assertEqual([p.name for p in community], ['Sunny FL Film', 'Flfilm Look Street Walk'])
        for preset in community:
            self.assertTrue(preset.source_url.startswith('https://sonyfilmsimulations.com/recipe/'))
        self.assertTrue(all('Sony Singapore' in p.source for p in recipes.PRESETS if p not in community))

    def test_unknown_preset(self):
        with self.assertRaises(KeyError):
            recipes.preset('Nope')


# ---------------------------------------------------------------- simulated α7C II body
LOOKS = tuple(range(0x0001, 0x000D))           # ST .. FL3
CUSTOM = tuple(range(0x0101, 0x0107))          # Custom Look 1-6
SLIDER_RANGES = {0xD0FB: (-9, 9), 0xD0FC: (-9, 9), 0xD0FD: (-9, 9), 0xD0FE: (0, 9),
                 0xD0FF: (-9, 9), 0xD100: (0, 9), 0xD101: (1, 5), 0xD102: (0, 9)}
DEFAULT_SLIDERS = {0xD0FB: 0, 0xD0FC: 0, 0xD0FD: 0, 0xD0FE: 0, 0xD0FF: 0, 0xD100: 0, 0xD101: 3, 0xD102: 0}
WB_MODES = (0x0002, 0x0004, 0x0006, 0x0007, 0x8010, 0x8011, 0x8012)
SHIFT_RANGE = (0x9C, 0xE4, 1)
BATTERY, FOCUS_MODE = 0xD218, 0x500A


class BodyCamera(FakeCamera):
    def tick_delayed(self):
        super().tick_delayed()
        self.props[BATTERY].current -= 1  # a read-only status value that changes on its own


class Body:
    """Camera-side model: sliders per look/slot, shifts per WB mode, BW/SE grey Saturation."""

    def __init__(self, *, looks=LOOKS, styles=LOOKS, picture_profile=0, look=0x0001, sliders=None,
                 drop=(), advertise_drop=(), **ranges):
        creative_enabled = 0 if picture_profile else 1
        props = [
            FakeProp(0xD23F, 2, picture_profile, enum_set=tuple(range(12))),
            FakeProp(0xD25A, 2, 0, enum_set=(0, 1)),
            FakeProp(0xD0FA, 4, look, enum_set=looks + CUSTOM, enabled=creative_enabled),
            FakeProp(0xD103, 4, 0x0001, enum_set=styles, enabled=0),
            *(FakeProp(code, 1, DEFAULT_SLIDERS[code], rng=ranges.get('range_%04X' % code, (low, high, 1)),
                       enabled=creative_enabled) for code, (low, high) in SLIDER_RANGES.items()),
            FakeProp(0x5005, 4, 0x0002, enum_set=WB_MODES),
            FakeProp(0xD20F, 4, 5500, rng=(2500, 9900, 100), enabled=0),
            FakeProp(0xD21C, 2, 0xC0, rng=ranges.get('range_D21C', SHIFT_RANGE)),
            FakeProp(0xD210, 2, 0xC0, rng=SHIFT_RANGE),
            FakeProp(0xD201, 2, 0x01, enum_set=(0x01, 0x11, 0x12, 0x13, 0x14, 0x15, 0x1F)),
            FakeProp(BATTERY, 1, 80, get_set=0, rng=(-1, 100, 1)),
            FakeProp(FOCUS_MODE, 4, 0x0002, enum_set=(0x0002, 0x8004, 0x8005)),
        ]
        props = [p for p in props if p.code not in drop]
        codes = [p.code for p in props if p.code not in advertise_drop]
        self.camera = BodyCamera(props, advertise=codes)
        self.sliders = {look: {**DEFAULT_SLIDERS, **(sliders or {})}}
        self.styles = {slot: 0x0001 for slot in CUSTOM}
        self.shifts = {0x0002: {0xD21C: 0xC0, 0xD210: 0xC0}}
        self.camera.after_write.append(self.react)
        self.load_look()

    def prop(self, code):
        return self.camera.props[code]

    def react(self, camera, code, value):
        look = self.prop(0xD0FA).current
        if code in SLIDER_RANGES:
            self.sliders.setdefault(look, dict(DEFAULT_SLIDERS))[code] = self.prop(code).current
        elif code == 0xD103 and look in CUSTOM:
            self.styles[look] = self.prop(code).current
            self.load_look()
        elif code == 0xD0FA:
            self.load_look()
        elif code in (0xD21C, 0xD210):
            self.shifts.setdefault(self.prop(0x5005).current, {})[code] = self.prop(code).current
        elif code == 0x5005:
            stored = self.shifts.setdefault(self.prop(0x5005).current, {0xD21C: 0xC0, 0xD210: 0xC0})
            for shift_code, wire in stored.items():
                self.prop(shift_code).current = wire
            self.prop(0xD20F).enabled = 1 if self.prop(0x5005).current == 0x8012 else 0

    def load_look(self):
        look = self.prop(0xD0FA).current
        for code, value in self.sliders.setdefault(look, dict(DEFAULT_SLIDERS)).items():
            if code in self.camera.props:
                self.prop(code).current = value
        custom = look in CUSTOM
        self.prop(0xD103).enabled = 1 if custom else 0
        if custom:
            self.prop(0xD103).current = self.styles[look]
        style = self.styles[look] if custom else look
        if 0xD0FF in self.camera.props and self.prop(0xD0FA).enabled:
            self.prop(0xD0FF).enabled = 0 if style in (0x0009, 0x000A) else 1

    def session(self, **kw):
        session, clock = connected(self.camera, **kw)
        return session


def snapshot_of(body):
    session = body.session()
    snapshot = session.read_all()
    body.camera.commands.clear()
    return snapshot


def step_codes(planned):
    return ['reread' if isinstance(s, recipes.ReRead) else s.code for s in planned.steps]


SLIDER_CODES = [0xD0FB, 0xD0FC, 0xD0FD, 0xD0FE, 0xD0FF, 0xD100, 0xD101, 0xD102]


class PlanTests(unittest.TestCase):
    def test_slot_target_order_with_re_read_markers(self):
        recipe = dataclasses.replace(recipes.preset('Sunny FL Film'), target=2)
        planned = recipes.plan(recipe, snapshot_of(Body()))
        self.assertTrue(planned.ok, planned.problems)
        self.assertEqual(step_codes(planned), [0xD25A, 0xD0FA, 0xD103, 'reread', *SLIDER_CODES,
                                               0x5005, 'reread', 0xD21C, 0xD210, 0xD201])
        writes = {w.code: w for w in planned.writes}
        self.assertEqual((writes[0xD25A].value, writes[0xD0FA].value, writes[0xD103].value), (1, 0x0102, 0x0006))
        self.assertTrue(writes[0xD103].provisional and writes[0xD0FB].provisional and writes[0xD21C].provisional)
        self.assertFalse(writes[0xD0FA].provisional or writes[0x5005].provisional or writes[0xD201].provisional)
        self.assertEqual((writes[0x5005].value, writes[0xD21C].value, writes[0xD210].value, writes[0xD201].value),
                         (0x8011, 0xC4, 0xC4, 0x1F))
        self.assertEqual(writes[0xD0FA].describe(), 'Creative Look: ST → Custom Look 2')

    def test_base_look_target_selects_the_look_without_a_style(self):
        planned = recipes.plan(recipes.preset('Retro Negative'), snapshot_of(Body()))
        self.assertEqual(step_codes(planned), [0xD25A, 0xD0FA, 'reread', *SLIDER_CODES, 0xD21C, 0xD210])
        self.assertEqual(planned.targets[0xD0FA], 0x0006)
        self.assertNotIn(0xD103, planned.targets)

    def test_values_already_on_the_camera_are_skipped(self):
        body = Body(look=0x0006, sliders={0xD0FB: -2, 0xD0FC: -2, 0xD0FD: -2, 0xD0FE: 2, 0xD101: 1, 0xD102: 1})
        body.prop(0xD25A).current = 1
        body.prop(0xD21C).current = 0xB8
        planned = recipes.plan(recipes.preset('Retro Negative'), snapshot_of(body))
        self.assertEqual(step_codes(planned), [0xD0FF, 0xD210])  # saturation +2, shift M0.25
        self.assertEqual({code for code, _ in planned.unchanged},
                         {0xD25A, 0xD0FA, 0xD0FB, 0xD0FC, 0xD0FD, 0xD0FE, 0xD100, 0xD101, 0xD102, 0xD21C})
        self.assertEqual(planned.writes[0].describe(), 'Saturation: 0 → +2')

    def test_colour_temperature_only_with_c_temp(self):
        ctemp = dataclasses.replace(recipes.preset('Sunny FL Film'), white_balance='C.Temp', kelvin=5600)
        planned = recipes.plan(ctemp, snapshot_of(Body(look=0x0006)))
        self.assertEqual(step_codes(planned)[-6:], [0x5005, 'reread', 0xD20F, 0xD21C, 0xD210, 0xD201])
        shade = recipes.plan(recipes.preset('Sunny FL Film'), snapshot_of(Body(look=0x0006)))
        self.assertNotIn(0xD20F, step_codes(shade))
        self.assertNotIn(0xD20F, shade.targets)

    def test_picture_profile_on_is_a_blocker_and_is_never_written(self):
        planned = recipes.plan(recipes.preset('Retro Negative'), snapshot_of(Body(picture_profile=3)))
        self.assertFalse(planned.ok)
        reasons = [p.reason for p in planned.blockers]
        self.assertTrue(any('PP3' in r and 'turn it off' in r for r in reasons), reasons)
        self.assertTrue(any(p.code == 0xD0FA and 'greyed out' in p.reason for p in planned.blockers))
        self.assertNotIn(0xD23F, [w.code for w in planned.writes])
        self.assertNotIn(0xD0FB, [w.code for w in planned.writes])

    def test_fl3_not_offered_by_this_body(self):
        older = Body(looks=LOOKS[:10], styles=LOOKS[:10])
        planned = recipes.plan(recipes.preset('Vintage Chrome'), snapshot_of(older))
        self.assertFalse(planned.ok)
        self.assertEqual([p.reason for p in planned.blockers], ['FL3 is not offered by this camera'])
        self.assertEqual([w.code for w in planned.writes], [0xD25A, 0xD21C, 0xD210])  # no slider for a look it cannot select
        slotted = recipes.plan(dataclasses.replace(recipes.preset('Vintage Chrome'), target=1), snapshot_of(older))
        self.assertEqual([(p.code, p.reason) for p in slotted.blockers], [(0xD103, 'FL3 is not offered by this camera')])

    def test_custom_slot_not_offered(self):
        body = Body()
        body.prop(0xD0FA).enum_set = LOOKS
        planned = recipes.plan(dataclasses.replace(recipes.preset('Retro Negative'), target=4), snapshot_of(body))
        self.assertEqual([p.reason for p in planned.blockers], ['Custom Look 4 is not offered by this camera'])

    def test_property_missing_from_the_camera_list(self):
        for kw in (dict(drop=(0xD102,)), dict(advertise_drop=(0xD102,))):
            with self.subTest(kw):
                planned = recipes.plan(recipes.preset('Retro Negative'), snapshot_of(Body(**kw)))
                self.assertEqual([(p.code, p.label) for p in planned.blockers], [(0xD102, 'Clarity')])
                self.assertIn('not offered', planned.blockers[0].reason)
                self.assertNotIn(0xD102, [w.code for w in planned.writes])

    def test_not_settable_greyed_and_out_of_camera_range(self):
        body = Body()
        body.prop(0xD201).get_set = 0
        planned = recipes.plan(recipes.preset('Sunny FL Film'), snapshot_of(body))
        self.assertIn('read-only', planned.blockers[0].reason)
        body = Body()
        body.prop(0xD201).enabled = 0
        planned = recipes.plan(recipes.preset('Sunny FL Film'), snapshot_of(body))
        self.assertEqual(planned.blockers[0].code, 0xD201)
        self.assertIn('greyed out', planned.blockers[0].reason)
        planned = recipes.plan(recipes.preset('Vintage Film'), snapshot_of(Body(range_D0FE=(0, 3, 1))))
        self.assertEqual(planned.blockers[0].code, 0xD0FE)
        self.assertIn('outside the camera range 0..3', planned.blockers[0].reason)

    def test_monochrome_look_never_writes_saturation(self):
        mono = recipes.Recipe('Mono', 'BW', 2, 0, 0, 0, 0, 0, 1, 0)
        planned = recipes.plan(mono, snapshot_of(Body()))
        self.assertTrue(planned.ok)
        self.assertNotIn(0xD0FF, [w.code for w in planned.writes])
        self.assertNotIn(0xD0FF, planned.targets)
        self.assertEqual([(p.code, p.blocking) for p in planned.problems], [(0xD0FF, False)])

    def test_wb_shift_range_not_centred_on_c0_is_refused(self):
        planned = recipes.plan(recipes.preset('Retro Negative'), snapshot_of(Body(range_D21C=(0x00, 0x48, 1))))
        self.assertEqual([p.code for p in planned.blockers], [0xD21C])
        self.assertIn('unconfirmed', planned.blockers[0].reason)

    def test_missing_position_key_is_reported_but_not_blocking(self):
        planned = recipes.plan(recipes.preset('Retro Negative'), snapshot_of(Body(drop=(0xD25A,))))
        self.assertTrue(planned.ok)
        self.assertEqual([(p.code, p.blocking) for p in planned.problems], [(0xD25A, False)])
        self.assertNotIn(0xD25A, [w.code for w in planned.writes])

    def test_every_preset_plans_cleanly_on_a_full_body(self):
        for preset in recipes.PRESETS:
            for target in (None, 6):
                with self.subTest(preset.name, target=target):
                    planned = recipes.plan(dataclasses.replace(preset, target=target), snapshot_of(Body()))
                    self.assertTrue(planned.ok, planned.problems)
                    advertised = Body().camera.advertise
                    self.assertTrue(all(w.code in advertised for w in planned.writes))


def written_codes(camera):
    return [code for code, _ in camera.writes()]


class ApplyTests(unittest.TestCase):
    def plan_and_session(self, body, recipe, **kw):
        session = body.session(**kw)
        planned = recipes.plan(recipe, session.read_all())
        body.camera.commands.clear()
        return session, planned

    def test_slot_recipe_is_written_verified_and_diffed(self):
        body = Body()
        session, planned = self.plan_and_session(body, dataclasses.replace(recipes.preset('Sunny FL Film'), target=2))
        result = recipes.apply(session, planned)
        expected = [0xD25A, 0xD0FA, 0xD103, 0xD0FB, 0xD0FC, 0xD0FD, 0xD0FF, 0xD101, 0x5005, 0xD21C, 0xD210, 0xD201]
        self.assertEqual([c.write.code for c in result.completed], expected)
        self.assertEqual(written_codes(body.camera), expected)  # fade, sharpness, clarity already matched slot 2
        self.assertTrue(all(c.sent for c in result.completed))
        state = {code: body.prop(code).current for code in (0xD0FA, 0xD103, 0xD0FB, 0xD0FC, 0xD0FD, 0xD0FE, 0xD0FF,
                                                           0xD100, 0xD101, 0xD102, 0x5005, 0xD21C, 0xD210, 0xD201)}
        self.assertEqual(state, {0xD0FA: 0x0102, 0xD103: 0x0006, 0xD0FB: 3, 0xD0FC: -9, 0xD0FD: 6, 0xD0FE: 0,
                                 0xD0FF: 1, 0xD100: 0, 0xD101: 1, 0xD102: 0, 0x5005: 0x8011, 0xD21C: 0xC4,
                                 0xD210: 0xC4, 0xD201: 0x1F})
        self.assertEqual(result.final.properties[0xD0FB].current, 3)
        self.assertNotIn(0x9207, body.camera.opcodes)
        self.assertEqual(body.prop(0xD23F).current, 0)

    def test_every_write_is_preceded_by_a_fresh_read(self):
        body = Body()
        session, planned = self.plan_and_session(body, recipes.preset('Retro Negative'))
        recipes.apply(session, planned)
        opcodes = body.camera.opcodes
        for index, opcode in enumerate(opcodes):
            if opcode == 0x9205:
                self.assertEqual(opcodes[index - 1], 0x9251)

    def test_camera_already_matching_needs_no_write(self):
        body = Body()
        session, planned = self.plan_and_session(body, recipes.preset('Retro Negative'))
        recipes.apply(session, planned)
        planned = recipes.plan(recipes.preset('Retro Negative'), session.read_all())
        body.camera.commands.clear()
        self.assertEqual(planned.steps, ())
        self.assertEqual(recipes.apply(session, planned).completed, ())
        self.assertNotIn(0x9205, body.camera.opcodes)

    def test_blocked_plan_sends_nothing(self):
        body = Body(picture_profile=3)
        session, planned = self.plan_and_session(body, recipes.preset('Retro Negative'))
        with self.assertRaisesRegex(recipes.ApplyError, 'blocker') as caught:
            recipes.apply(session, planned)
        self.assertEqual(body.camera.commands, [])
        self.assertTrue(caught.exception.problems)
        self.assertEqual(caught.exception.completed, ())

    def test_stale_plan_sends_nothing(self):
        body = Body()
        session, planned = self.plan_and_session(body, recipes.preset('Sunny FL Film'))
        body.prop(0x5005).current = 0x0004  # someone turned the WB dial after the plan was shown
        with self.assertRaisesRegex(recipes.ApplyError, 'changed since'):
            recipes.apply(session, planned)
        self.assertEqual(body.camera.opcodes, [0x9209])

    def test_stops_at_the_first_failure_with_the_exact_completed_list(self):
        body = Body()
        body.camera.ignore_writes.add(0xD0FD)  # Shadows: answered OK, never applied
        session, planned = self.plan_and_session(body, recipes.preset('Retro Negative'), readback_timeout=1.0)
        with self.assertRaises(recipes.ApplyError) as caught:
            recipes.apply(session, planned)
        error = caught.exception
        self.assertEqual([c.write.code for c in error.completed], [0xD25A, 0xD0FA, 0xD0FB, 0xD0FC])
        self.assertEqual([(c.before, c.after) for c in error.completed], [(0, 1), (0x0001, 0x0006), (0, -2), (0, -2)])
        self.assertEqual((error.failed.code, error.outcome), (0xD0FD, 'not_applied'))
        self.assertEqual(written_codes(body.camera), [0xD25A, 0xD0FA, 0xD0FB, 0xD0FC, 0xD0FD])
        self.assertIn('Shadows', str(error))
        self.assertIn('Completed writes: Position Key, Creative Look, Contrast, Highlights', str(error))

    def test_unknown_outcome_stops_and_nothing_more_is_sent(self):
        body = Body()
        answers = iter(range(100))
        body.camera.mangle[0x9205] = lambda out: [] if next(answers) == 2 else out
        session, planned = self.plan_and_session(body, recipes.preset('Retro Negative'))
        with self.assertRaises(recipes.ApplyError) as caught:
            recipes.apply(session, planned)
        self.assertEqual([c.write.code for c in caught.exception.completed], [0xD25A, 0xD0FA])
        self.assertEqual((caught.exception.failed.code, caught.exception.outcome), (0xD0FB, 'unknown'))
        self.assertEqual(written_codes(body.camera), [0xD25A, 0xD0FA, 0xD0FB])
        self.assertFalse(session.usable)

    def test_rejected_write_is_reported_as_rejected(self):
        body = Body()
        session, planned = self.plan_and_session(body, recipes.preset('Retro Negative'))
        # The first write (Position Key) is answered normally; the next one gets Parameter Not Supported.
        body.camera.after_write.append(lambda camera, code, value: camera.respond.__setitem__(0x9205, [0x2006]))
        with self.assertRaises(recipes.ApplyError) as caught:
            recipes.apply(session, planned)
        self.assertEqual((caught.exception.failed.code, caught.exception.outcome), (0xD0FA, 'rejected'))
        self.assertEqual([c.write.code for c in caught.exception.completed], [0xD25A])

    def test_selector_reverted_after_verification_is_detected_at_the_re_read(self):
        body = Body()

        def revert_later(camera, code, value):
            if code == 0xD0FA:
                camera.delayed.append((0xD0FA, 0x0001, 1))
        body.camera.after_write.append(revert_later)
        session, planned = self.plan_and_session(body, recipes.preset('Retro Negative'))
        with self.assertRaisesRegex(recipes.ApplyError, 'reverted Creative Look') as caught:
            recipes.apply(session, planned)
        self.assertEqual([c.write.code for c in caught.exception.completed], [0xD25A, 0xD0FA])
        self.assertEqual(written_codes(body.camera), [0xD25A, 0xD0FA])

    def test_blocker_discovered_after_the_re_read_stops_before_the_sliders(self):
        body = Body()

        def grey_clarity(camera, code, value):
            if code == 0xD0FA:
                camera.props[0xD102].enabled = 0
        body.camera.after_write.append(grey_clarity)
        session, planned = self.plan_and_session(body, recipes.preset('Retro Negative'))
        with self.assertRaisesRegex(recipes.ApplyError, 'Clarity') as caught:
            recipes.apply(session, planned)
        self.assertEqual([p.code for p in caught.exception.problems], [0xD102])
        self.assertEqual(written_codes(body.camera), [0xD25A, 0xD0FA])

    def test_final_diff_detects_an_unintended_change(self):
        body = Body()

        def side_effect(camera, code, value):
            if code == 0xD201:
                camera.props[FOCUS_MODE].current = 0x8004
        body.camera.after_write.append(side_effect)
        session, planned = self.plan_and_session(body, recipes.preset('Sunny FL Film'))
        with self.assertRaisesRegex(recipes.ApplyError, '0x500A') as caught:
            recipes.apply(session, planned)
        self.assertEqual(caught.exception.unexpected, (FOCUS_MODE,))
        self.assertEqual(caught.exception.completed[-1].write.code, 0xD201)  # every write had completed
        self.assertEqual(caught.exception.mismatched, ())

    def test_final_check_detects_a_disturbed_earlier_write(self):
        body = Body()

        def disturb(camera, code, value):
            if code == 0xD201:
                camera.props[0xD0FB].current = 0
        body.camera.after_write.append(disturb)
        session, planned = self.plan_and_session(body, recipes.preset('Sunny FL Film'))
        with self.assertRaisesRegex(recipes.ApplyError, 'Contrast') as caught:
            recipes.apply(session, planned)
        self.assertEqual(caught.exception.mismatched, ((0xD0FB, 3, 0),))
        self.assertEqual(caught.exception.unexpected, ())

    def test_status_values_and_greyed_dependents_are_not_unintended_changes(self):
        body = Body()  # battery drops on every read; BW greys and changes Saturation
        mono = recipes.Recipe('Mono', 'BW', 2, 0, 0, 0, 0, 0, 1, 0)
        body.sliders[0x0009] = {**DEFAULT_SLIDERS, 0xD0FF: 5}
        session, planned = self.plan_and_session(body, mono)
        result = recipes.apply(session, planned)
        self.assertNotEqual(result.final.properties[BATTERY].current, 80)
        self.assertEqual(result.final.properties[0xD0FF].enabled, 0)


class ChangedSettingsTests(unittest.TestCase):
    def test_only_settable_enabled_values_count(self):
        body = Body()
        before = snapshot_of(body)
        body.prop(BATTERY).current = 10        # read-only status
        body.prop(0xD20F).current = 3200       # greyed: value not guaranteed
        body.prop(FOCUS_MODE).current = 0x8005  # a real setting
        self.assertEqual(recipes.changed_settings(before, snapshot_of(body)), [FOCUS_MODE])

    def test_a_setting_that_appears_or_disappears_counts(self):
        before = snapshot_of(Body())
        after = snapshot_of(Body(drop=(FOCUS_MODE,)))
        self.assertEqual(recipes.changed_settings(before, after), [FOCUS_MODE])
        self.assertEqual(recipes.changed_settings(after, before), [FOCUS_MODE])
