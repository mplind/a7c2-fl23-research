"""Sony PC Remote (USB PTP) session, simulated byte for byte; never opens USB.

Expected bytes are written out from Sony's Camera Control PTP 3 Reference layouts
(containers p.44-45, SDIExtDeviceInfo p.118, SDIDevicePropInfo p.121-122) with
struct/hex in this file, never with the module's own encoders.
"""
import struct
import unittest

from camera_runtime import ptpremote as ptp


# ---------------------------------------------------------------- test-side encoders
INT_FORMATS = {1: '<b', 2: '<B', 3: '<h', 4: '<H', 5: '<i', 6: '<I', 7: '<q', 8: '<Q'}


def ptp_str(text):
    """PTP string: u8 count of UTF-16 units including NUL, then the units."""
    if text == '':
        return b'\x00'
    units = (text + '\0').encode('utf-16-le')
    return bytes([len(units) // 2]) + units


def value_bytes(datatype, value):
    return ptp_str(value) if datatype == 0xFFFF else struct.pack(INT_FORMATS[datatype], value)


def arr16(codes):
    return struct.pack('<I', len(codes)) + b''.join(struct.pack('<H', c) for c in codes)


def record(code, datatype, get_set, enabled, default, current, form=0, rng=None, enum_set=(), enum_get_set=()):
    data = struct.pack('<HHBB', code, datatype, get_set, enabled)
    data += value_bytes(datatype, default) + value_bytes(datatype, current) + bytes([form])
    if form == 1:
        data += b''.join(value_bytes(datatype, v) for v in rng)
    elif form == 2:
        data += struct.pack('<H', len(enum_set)) + b''.join(value_bytes(datatype, v) for v in enum_set)
        data += struct.pack('<H', len(enum_get_set)) + b''.join(value_bytes(datatype, v) for v in enum_get_set)
    return data


def dataset(*records):
    return struct.pack('<Q', len(records)) + b''.join(records)


class ContainerTests(unittest.TestCase):
    def test_command_container_is_length_type_code_tid_params(self):
        self.assertEqual(ptp.pack_command(0x1002, 0, (1,)),
                         bytes.fromhex('10000000' '0100' '0210' '00000000' '01000000'))

    def test_command_without_parameters_is_twelve_bytes(self):
        self.assertEqual(ptp.pack_command(0x1001, 0, ()), bytes.fromhex('0c000000' '0100' '0110' '00000000'))

    def test_command_refuses_more_than_five_parameters(self):
        with self.assertRaises(ValueError):
            ptp.pack_command(0x9201, 1, (1, 2, 3, 4, 5, 6))

    def test_data_container_carries_opcode_and_tid(self):
        self.assertEqual(ptp.pack_container(ptp.DATA, 0x9205, 7, b'\xfe'),
                         bytes.fromhex('0d000000' '0200' '0592' '07000000' 'fe'))

    def test_response_container_unpacks_code_tid_and_params(self):
        container = ptp.unpack_container(bytes.fromhex('14000000' '0300' '0120' '05000000' '2c010000' '00000000'))
        self.assertEqual((container.kind, container.code, container.tid), (ptp.RESPONSE, 0x2001, 5))
        self.assertEqual(container.params, (0x012C, 0))

    def test_malformed_containers_fail_closed(self):
        bad = {
            'short header': bytes.fromhex('0c000000' '0300' '0120'),
            'length mismatch': bytes.fromhex('10000000' '0300' '0120' '05000000'),
            'unknown type': bytes.fromhex('0c000000' '0900' '0120' '05000000'),
            'ragged response params': bytes.fromhex('0e000000' '0300' '0120' '05000000' '0102'),
            'too many response params': bytes.fromhex('24000000' '0300' '0120' '05000000') + bytes(24),
        }
        for name, data in bad.items():
            with self.subTest(name), self.assertRaises(ptp.ProtocolError):
                ptp.unpack_container(data)


class OperationGateTests(unittest.TestCase):
    ADVERTISED = frozenset({0x1001, 0x1002, 0x1003, 0x9201, 0x9202, 0x9205, 0x9207, 0x9209, 0x9216, 0x100B, 0x9251})

    def check(self, opcode, operations=ADVERTISED):
        ptp.check_operation(opcode, operations)

    def test_allow_listed_and_advertised_operations_pass(self):
        for opcode in (0x1001, 0x1002, 0x1003, 0x9201, 0x9202, 0x9205, 0x9209, 0x9251):
            with self.subTest(hex(opcode)):
                self.check(opcode)

    def test_advertised_but_not_allow_listed_operations_are_refused(self):
        # DeleteObject; ControlDevice (e.g. Reset Creative Look) and GetVendorCodeVersion, which nothing here sends
        for opcode in (0x100B, 0x9207, 0x9216):
            with self.subTest(hex(opcode)), self.assertRaisesRegex(ptp.OperationRefused, '0x%04X' % opcode):
                self.check(opcode)

    def test_allow_listed_but_unadvertised_operation_is_refused(self):
        with self.assertRaisesRegex(ptp.OperationRefused, 'did not advertise'):
            self.check(0x9251, self.ADVERTISED - {0x9251})

    def test_only_get_device_info_is_possible_before_the_device_list_is_known(self):
        ptp.check_operation(0x1001, None)
        with self.assertRaises(ptp.OperationRefused):
            ptp.check_operation(0x1002, None)


# Contrast 0xD0FB, INT8, settable, enabled, default 0, current -2, Range -9..+9 step 1 (p.121, p.309).
CONTRAST_RECORD = bytes.fromhex('fbd0' '0100' '01' '01' '00' 'fe' '01' 'f7' '09' '01')
# Creative Look 0xD0FA, UINT16, default ST, current FL, Enum Set [ST, FL, Custom1], Get/Set [ST, FL, Custom1, FL3].
LOOK_RECORD = bytes.fromhex('fad0' '0400' '01' '01' '0100' '0600' '02'
                            '0300' '0100' '0600' '0101'
                            '0400' '0100' '0600' '0101' '0c00')
# Software version 0xD040, STR, read-only, default '' and current '2.01'.
VERSION_RECORD = bytes.fromhex('40d0' 'ffff' '00' '01' '00' '05' '3200' '2e00' '3000' '3100' '0000' '00')


class DatasetTests(unittest.TestCase):
    def test_int8_range_record_decodes_negative_values(self):
        props, _ = ptp.parse_all_properties(bytes.fromhex('0100000000000000') + CONTRAST_RECORD)
        contrast = props[0xD0FB]
        self.assertEqual((contrast.datatype, contrast.get_set, contrast.enabled), (ptp.INT8, 1, 1))
        self.assertEqual((contrast.default, contrast.current), (0, -2))
        self.assertEqual((contrast.form, contrast.minimum, contrast.maximum, contrast.step), (ptp.FORM_RANGE, -9, 9, 1))

    def test_uint16_enum_record_keeps_both_lists(self):
        props, _ = ptp.parse_all_properties(bytes.fromhex('0100000000000000') + LOOK_RECORD)
        look = props[0xD0FA]
        self.assertEqual((look.default, look.current, look.form), (0x0001, 0x0006, ptp.FORM_ENUM))
        self.assertEqual(look.enum_set, (0x0001, 0x0006, 0x0101))
        self.assertEqual(look.enum_get_set, (0x0001, 0x0006, 0x0101, 0x000C))

    def test_string_record(self):
        props, _ = ptp.parse_all_properties(bytes.fromhex('0100000000000000') + VERSION_RECORD)
        self.assertEqual((props[0xD040].default, props[0xD040].current, props[0xD040].form), ('', '2.01', ptp.FORM_NONE))

    def test_several_records_parse_to_the_exact_end(self):
        props, controls = ptp.parse_all_properties(dataset(CONTRAST_RECORD, LOOK_RECORD, VERSION_RECORD))
        self.assertEqual(sorted(props), [0xD040, 0xD0FA, 0xD0FB])
        self.assertEqual(controls, {})

    def test_all_integer_widths_and_signs(self):
        rows = [record(0xD001, 1, 1, 1, -128, 127), record(0xD002, 2, 1, 1, 0, 255),
                record(0xD003, 3, 1, 1, -32768, 32767), record(0xD004, 4, 1, 1, 0, 65535),
                record(0xD005, 5, 1, 1, -2 ** 31, 2 ** 31 - 1), record(0xD006, 6, 1, 1, 0, 2 ** 32 - 1),
                record(0xD007, 7, 1, 1, -2 ** 63, 2 ** 63 - 1), record(0xD008, 8, 1, 1, 0, 2 ** 64 - 1)]
        props, _ = ptp.parse_all_properties(dataset(*rows))
        self.assertEqual([(props[c].default, props[c].current) for c in range(0xD001, 0xD009)],
                         [(-128, 127), (0, 255), (-32768, 32767), (0, 65535), (-2 ** 31, 2 ** 31 - 1),
                          (0, 2 ** 32 - 1), (-2 ** 63, 2 ** 63 - 1), (0, 2 ** 64 - 1)])

    def test_uint16_array_values(self):
        # AUINT16 (0x4004): u32 count then elements; default [1, 2], current [], no form.
        raw = bytes.fromhex('0ae0' '0440' '00' '01' '02000000' '0100' '0200' '00000000' '00')
        props, _ = ptp.parse_all_properties(dataset(raw))
        self.assertEqual((props[0xE00A].default, props[0xE00A].current), ((1, 2), ()))

    def test_control_record_shape_is_used_for_advertised_control_codes(self):
        # 0xD306 Reset Creative Look: code, UINT16, type 0x81 button, enabled, 4 reserved, form 2 (p.680).
        control = bytes.fromhex('06d3' '0400' '81' '01' '00000000' '02')
        props, controls = ptp.parse_all_properties(dataset(CONTRAST_RECORD, control, LOOK_RECORD),
                                                   control_codes={0xD306})
        self.assertEqual(sorted(props), [0xD0FA, 0xD0FB])
        self.assertEqual((controls[0xD306].datatype, controls[0xD306].control_type, controls[0xD306].enabled),
                         (ptp.UINT16, 0x81, 1))

    def test_single_property_dataset_from_get_ext_device_prop(self):
        self.assertEqual(ptp.parse_property(LOOK_RECORD).current, 0x0006)

    def test_fail_closed_cases(self):
        bad = {
            'trailing byte': dataset(CONTRAST_RECORD) + b'\x00',
            'missing byte': dataset(CONTRAST_RECORD)[:-1],
            'missing second enum list': dataset(LOOK_RECORD[:-10]),
            'count larger than records': struct.pack('<Q', 2) + CONTRAST_RECORD,
            'count smaller than records': struct.pack('<Q', 1) + CONTRAST_RECORD + LOOK_RECORD,
            'unknown datatype': dataset(bytes.fromhex('fbd0' '4200' '01' '01' '00' '00' '00')),
            'unknown form flag': dataset(bytes.fromhex('fbd0' '0100' '01' '01' '00' '00' '03')),
            'string without NUL': dataset(bytes.fromhex('40d0' 'ffff' '00' '01' '00' '02' '3200' '3200' '00')),
            'duplicate code': dataset(CONTRAST_RECORD, CONTRAST_RECORD),
            'empty buffer': b'',
            'absurd count': struct.pack('<Q', 2 ** 40),
            'enum count beyond buffer': dataset(bytes.fromhex('fad0' '0400' '01' '01' '0100' '0100' '02' 'ffff')),
        }
        for name, data in bad.items():
            with self.subTest(name), self.assertRaises(ptp.DatasetError):
                ptp.parse_all_properties(data)
        for name, data in {'trailing': LOOK_RECORD + b'\x00', 'short': LOOK_RECORD[:-1], 'empty': b''}.items():
            with self.subTest('single ' + name), self.assertRaises(ptp.DatasetError):
                ptp.parse_property(data)

    def test_a_code_in_both_advertised_lists_is_ambiguous(self):
        with self.assertRaisesRegex(ptp.DatasetError, 'both'):
            ptp.parse_all_properties(dataset(CONTRAST_RECORD), control_codes={0xD0FB}, property_codes={0xD0FB})


class DescriptorRuleTests(unittest.TestCase):
    """What a fresh descriptor allows; the same rules gate set_property and recipe plans."""

    def parse(self, raw):
        return ptp.parse_property(raw)

    def test_range_value_must_be_within_bounds_and_on_step(self):
        sharpness_range = self.parse(record(0xD101, 1, 1, 1, 1, 1, 1, (1, 5, 2)))  # 1, 3, 5 allowed
        self.assertIsNone(sharpness_range.refusal(3))
        self.assertIn('outside', sharpness_range.refusal(6))
        self.assertIn('outside', sharpness_range.refusal(0))
        self.assertIn('step', sharpness_range.refusal(2))

    def test_enum_value_must_be_in_both_lists(self):
        look = self.parse(LOOK_RECORD)
        self.assertEqual(look.settable_values, (0x0001, 0x0006, 0x0101))
        self.assertIsNone(look.refusal(0x0101))
        self.assertIn('not offered', look.refusal(0x000C))  # only in the Get/Set list
        self.assertIn('not offered', look.refusal(0x000B))
        # A value only in the first ("Set") list is refused too: sources disagree on which list rules.
        dro = self.parse(record(0xD201, 2, 1, 1, 1, 1, 2, enum_set=(0x01, 0x1F), enum_get_set=(0x01,)))
        self.assertEqual(dro.settable_values, (0x01,))
        self.assertIn('not offered', dro.refusal(0x1F))

    def test_read_only_greyed_and_display_only_are_refused(self):
        self.assertIn('read-only', self.parse(record(0xD0FB, 1, 0, 1, 0, 0, 1, (-9, 9, 1))).refusal(1))
        self.assertIn('greyed out', self.parse(record(0xD0FF, 1, 1, 0, 0, 0, 1, (-9, 9, 1))).refusal(1))
        self.assertIn('display-only', self.parse(record(0xD0FF, 1, 1, 2, 0, 0, 1, (-9, 9, 1))).refusal(1))

    def test_enabled_check_can_be_deferred_for_a_planned_selector_change(self):
        greyed = self.parse(record(0xD0FF, 1, 1, 0, 0, 0, 1, (-9, 9, 1)))
        self.assertIsNone(greyed.refusal(1, require_enabled=False))
        self.assertIn('outside', greyed.refusal(10, require_enabled=False))

    def test_unwritable_forms_and_types_are_refused(self):
        self.assertIn('no range or list', self.parse(record(0xD0FB, 1, 1, 1, 0, 0)).refusal(0))
        self.assertIn('step', self.parse(record(0xD0FB, 1, 1, 1, 0, 0, 1, (-9, 9, 0))).refusal(0))
        self.assertIn('datatype', self.parse(record(0xD040, 0xFFFF, 1, 1, '', '', 0)).refusal('x'))
        self.assertIn('integer', self.parse(record(0xD0FB, 1, 1, 1, 0, 0, 1, (-9, 9, 1))).refusal(True))
        self.assertIn('integer', self.parse(record(0xD0FB, 1, 1, 1, 0, 0, 1, (-9, 9, 1))).refusal(1.0))


# ---------------------------------------------------------------- fake camera
SONY_OPERATIONS = (0x1001, 0x1002, 0x1003, 0x9201, 0x9202, 0x9205, 0x9207, 0x9209, 0x9251)


def device_info_bytes(operations, manufacturer='Sony Corporation', model='ILCE-7CM2'):
    """PIMA 15740 DeviceInfo dataset."""
    return (struct.pack('<HIH', 100, 0x00000011, 100) + ptp_str('') + struct.pack('<H', 0)
            + arr16(operations) + arr16([0xC201]) + arr16([0x5005]) + arr16([]) + arr16([0x3801])
            + ptp_str(manufacturer) + ptp_str(model) + ptp_str('2.01') + ptp_str('0123456789'))


class FakeProp:
    """Mutable camera-side state of one property; renders its own dataset bytes."""

    def __init__(self, code, datatype, current, *, get_set=1, enabled=1, default=None, rng=None,
                 enum_set=None, enum_get_set=None):
        self.code, self.datatype, self.current = code, datatype, current
        self.get_set, self.enabled = get_set, enabled
        self.default = current if default is None else default
        self.rng, self.enum_set = rng, enum_set
        self.enum_get_set = enum_set if enum_get_set is None else enum_get_set

    def record(self):
        form = 1 if self.rng else 2 if self.enum_set is not None else 0
        return record(self.code, self.datatype, self.get_set, self.enabled, self.default, self.current,
                      form, self.rng, self.enum_set or (), self.enum_get_set or ())


class FakeClock:
    def __init__(self):
        self.now, self.sleeps = 1000.0, []

    def time(self):
        return self.now

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.now += seconds


class FakeCamera:
    """Container-level stand-in for a PC Remote body, behind ptpremote's Transport interface.

    Knobs: `respond[opcode]` queues response codes used instead of handling the
    command; `ignore_writes`/`coerce`/`delay_writes` model a camera that answers OK
    without (or late in) applying; `after_write` callbacks model side effects;
    `mangle[opcode]` edits the reply containers; `silent` opcodes never answer.
    """

    def __init__(self, props=(), *, operations=SONY_OPERATIONS, controls=(0xD306,), version=0x012C,
                 manufacturer='Sony Corporation', model='ILCE-7CM2', empty_ext_info=0, connect_data=bytes(8),
                 advertise=None):
        self.props = {p.code: p for p in props}
        self.operations, self.controls, self.version = tuple(operations), tuple(controls), version
        self.manufacturer, self.model = manufacturer, model
        self.advertise = tuple(self.props) if advertise is None else tuple(advertise)
        self.empty_ext_info, self.connect_data = empty_ext_info, connect_data
        self.commands, self.replies, self.pending = [], [], None
        self.respond, self.mangle, self.silent = {}, {}, set()
        self.ignore_writes, self.coerce, self.delay_writes, self.after_write = set(), {}, {}, []
        self.delayed = []
        self.closed = False

    @property
    def opcodes(self):
        return [c[0] for c in self.commands]

    def writes(self):
        return [(c[2][0], c[3]) for c in self.commands if c[0] == 0x9205]

    # Transport interface
    def send(self, data, timeout):
        length, kind, code, tid = struct.unpack_from('<IHHI', data)
        assert length == len(data) and timeout > 0
        if kind == 1:
            params = struct.unpack_from('<%dI' % ((length - 12) // 4), data, 12)
            if code == 0x9205:
                self.pending = (code, tid, params)
                return
            self.commands.append((code, tid, params, None))
            self.answer(code, tid, params, None)
        else:
            assert kind == 2 and self.pending and self.pending[:2] == (code, tid), 'unexpected data container'
            opcode, _, params = self.pending
            self.pending = None
            self.commands.append((opcode, tid, params, data[12:]))
            self.answer(opcode, tid, params, data[12:])

    def receive(self, timeout):
        assert timeout > 0
        if not self.replies:
            raise ptp.TransportTimeout('fake camera has nothing to send')
        return self.replies.pop(0)

    def close(self):
        self.closed = True

    # camera behaviour
    def reply(self, opcode, tid, code=0x2001, data=None, params=()):
        out = []
        if data is not None:
            out.append(struct.pack('<IHHI', 12 + len(data), 2, opcode, tid) + data)
        out.append(struct.pack('<IHHI', 12 + 4 * len(params), 3, code, tid) + struct.pack('<%dI' % len(params), *params))
        if opcode in self.mangle:
            out = self.mangle[opcode](out)
        if opcode not in self.silent:
            self.replies.extend(out)

    def tick_delayed(self):
        ready = [d for d in self.delayed if d[2] <= 0]
        self.delayed = [(c, v, n - 1) for c, v, n in self.delayed if n > 0]
        for code, value, _ in ready:
            self.props[code].current = value

    def answer(self, opcode, tid, params, payload):
        if self.respond.get(opcode):
            return self.reply(opcode, tid, self.respond[opcode].pop(0))
        if opcode == 0x1001:
            return self.reply(opcode, tid, data=device_info_bytes(self.operations, self.manufacturer, self.model))
        if opcode in (0x1002, 0x1003):
            return self.reply(opcode, tid)
        if opcode == 0x9201:
            return self.reply(opcode, tid, data=self.connect_data)
        if opcode == 0x9202:
            if self.empty_ext_info:
                self.empty_ext_info -= 1
                return self.reply(opcode, tid, data=b'', params=(0x012C,))
            data = struct.pack('<H', self.version) + arr16(self.advertise) + arr16(self.controls)
            return self.reply(opcode, tid, data=data, params=(0x012C,))
        if opcode == 0x9209:
            self.tick_delayed()
            return self.reply(opcode, tid, data=dataset(*(p.record() for p in self.props.values())))
        if opcode == 0x9251:
            self.tick_delayed()
            if params[0] not in self.props:
                return self.reply(opcode, tid, 0x2006)
            return self.reply(opcode, tid, data=self.props[params[0]].record())
        if opcode == 0x9205:
            prop = self.props[params[0]]
            value = struct.unpack(INT_FORMATS[prop.datatype], payload)[0]
            if prop.code in self.delay_writes:
                self.delayed.append((prop.code, value, self.delay_writes[prop.code]))
            elif prop.code in self.coerce:
                prop.current = self.coerce[prop.code]
            elif prop.code not in self.ignore_writes:
                prop.current = value
            for callback in self.after_write:
                callback(self, prop.code, value)
            return self.reply(opcode, tid)
        raise AssertionError('fake camera got unexpected operation 0x%04X' % opcode)


def contrast(current=0, **kw):
    return FakeProp(0xD0FB, 1, current, rng=(-9, 9, 1), **kw)


def creative_look(current=0x0001, **kw):
    kw.setdefault('enum_set', (0x0001, 0x0006, 0x0101))
    return FakeProp(0xD0FA, 4, current, **kw)


def session_for(camera, **kw):
    clock = FakeClock()
    session = ptp.RemoteSession(camera, clock=clock.time, sleep=clock.sleep, **kw)
    return session, clock


def connected(camera, **kw):
    session, clock = session_for(camera, **kw)
    session.connect()
    camera.commands.clear()
    return session, clock


class HandshakeParsingTests(unittest.TestCase):
    def test_device_info_dataset(self):
        info = ptp.parse_device_info(device_info_bytes((0x1001, 0x9201)))
        self.assertEqual((info.manufacturer, info.model, info.device_version), ('Sony Corporation', 'ILCE-7CM2', '2.01'))
        self.assertEqual(info.operations, frozenset({0x1001, 0x9201}))
        self.assertFalse(hasattr(info, 'serial_number'))  # never kept
        with self.assertRaises(ptp.DatasetError):
            ptp.parse_device_info(device_info_bytes((0x1001,)) + b'\x00')

    def test_ext_device_info_dataset(self):
        info = ptp.parse_ext_device_info(bytes.fromhex('2c01' '02000000' 'fad0' 'fbd0' '01000000' '06d3'))
        self.assertEqual((info.version, info.properties, info.controls), (0x012C, frozenset({0xD0FA, 0xD0FB}), frozenset({0xD306})))
        for bad in (bytes.fromhex('2c01' '02000000' 'fad0'), bytes.fromhex('2c01' '00000000' '00000000' '00')):
            with self.subTest(bad.hex()), self.assertRaises(ptp.DatasetError):
                ptp.parse_ext_device_info(bad)


class ConnectTests(unittest.TestCase):
    def test_connect_sequence_order_and_parameters(self):
        camera = FakeCamera([contrast()])
        session, _ = session_for(camera)
        info = session.connect()
        self.assertEqual([c[:3] for c in camera.commands], [
            (0x1001, 0, ()), (0x1002, 0, (1,)),
            (0x9201, 1, (1, 0, 0)), (0x9201, 2, (2, 0, 0)),
            (0x9202, 3, (0x012C,)),
            (0x9201, 4, (3, 0, 0))])
        self.assertEqual(info.ext.version, 0x012C)
        self.assertEqual(info.ext.properties, frozenset({0xD0FB}))
        self.assertEqual(info.ext.vendor_code_version, 0x012C)
        self.assertEqual(info.device.model, 'ILCE-7CM2')

    def test_empty_ext_device_info_is_retried_after_a_pause(self):
        camera = FakeCamera([contrast()], empty_ext_info=2)
        session, clock = session_for(camera)
        session.connect()
        self.assertEqual(camera.opcodes, [0x1001, 0x1002, 0x9201, 0x9201, 0x9202, 0x9202, 0x9202, 0x9201])
        self.assertEqual(clock.sleeps, [0.1, 0.1])

    def test_empty_ext_device_info_retry_is_bounded(self):
        camera = FakeCamera([contrast()], empty_ext_info=100)
        session, _ = session_for(camera, ext_info_attempts=3)
        with self.assertRaisesRegex(ptp.ConnectError, 'empty'):
            session.connect()
        self.assertEqual(camera.opcodes.count(0x9202), 3)
        self.assertNotIn((0x9201, (3, 0, 0)), [(c[0], c[2]) for c in camera.commands])
        self.assertEqual(camera.opcodes[-1], 0x1003)  # the half-open session is closed again
        self.assertTrue(camera.closed)

    def test_extension_version_mismatch_aborts_before_phase_three(self):
        camera = FakeCamera([contrast()], version=0x00C8)
        session, _ = session_for(camera)
        with self.assertRaisesRegex(ptp.ConnectError, '0x00C8'):
            session.connect()
        self.assertNotIn((0x9201, (3, 0, 0)), [(c[0], c[2]) for c in camera.commands])
        self.assertNotIn(0x9205, camera.opcodes)

    def test_wrong_body_stops_after_get_device_info(self):
        for kw in (dict(model='ILCE-7M4'), dict(manufacturer='Other Corp')):
            camera = FakeCamera([contrast()], **kw)
            session, _ = session_for(camera)
            with self.subTest(kw), self.assertRaises(ptp.ConnectError):
                session.connect()
            self.assertEqual(camera.opcodes, [0x1001])
            self.assertTrue(camera.closed)

    def test_missing_pc_remote_operations_stop_after_get_device_info(self):
        camera = FakeCamera([contrast()], operations=(0x1001, 0x1002, 0x1003, 0x9201, 0x9202, 0x9209))
        session, _ = session_for(camera)
        with self.assertRaisesRegex(ptp.ConnectError, '0x9205'):
            session.connect()
        self.assertEqual(camera.opcodes, [0x1001])

    def test_sdio_connect_must_return_its_eight_byte_data_phase(self):
        for data in (bytes(4), None, bytes(9)):
            camera = FakeCamera([contrast()], connect_data=data)
            session, _ = session_for(camera)
            with self.subTest(data), self.assertRaises(ptp.ProtocolError):
                session.connect()
            self.assertEqual(camera.opcodes, [0x1001, 0x1002, 0x9201])
            self.assertTrue(camera.closed)

    def test_session_already_open_is_closed_and_reopened_once(self):
        camera = FakeCamera([contrast()])
        camera.respond[0x1002] = [0x201E]
        session, _ = session_for(camera)
        session.connect()
        self.assertEqual(camera.opcodes[:4], [0x1001, 0x1002, 0x1003, 0x1002])
        camera = FakeCamera([contrast()])
        camera.respond[0x1002] = [0x201E, 0x201E]
        session, _ = session_for(camera)
        with self.assertRaises(ptp.ConnectError):
            session.connect()

    def test_context_manager_closes_session_and_transport(self):
        camera = FakeCamera([contrast()])
        clock = FakeClock()
        with ptp.RemoteSession(camera, clock=clock.time, sleep=clock.sleep) as session:
            self.assertTrue(session.connected)
        self.assertEqual(camera.opcodes[-1], 0x1003)
        self.assertTrue(camera.closed)


class ChokePointTests(unittest.TestCase):
    def test_unadvertised_operation_sends_nothing(self):
        camera = FakeCamera([contrast()], operations=(0x1001, 0x1002, 0x1003, 0x9201, 0x9202, 0x9205, 0x9209))
        session, _ = connected(camera)
        with self.assertRaises(ptp.OperationRefused):
            session._transact(0x9251, (0xD0FB,))
        self.assertEqual(camera.commands, [])

    def test_non_allow_listed_operations_send_nothing_even_when_advertised(self):
        camera = FakeCamera([contrast()], operations=SONY_OPERATIONS + (0x100B, 0x100C, 0x9280))
        session, _ = connected(camera)
        for opcode in (0x100B, 0x100C, 0x9280):
            with self.subTest(hex(opcode)), self.assertRaises(ptp.OperationRefused):
                session._transact(opcode, (1,))
        self.assertEqual(camera.commands, [])

    def test_control_device_is_never_sent(self):
        camera = FakeCamera([contrast()])
        session, _ = connected(camera)
        for params in ((0xD306,), (0xD2C1,)):  # not even Reset Creative Look
            with self.subTest(params), self.assertRaises(ptp.OperationRefused):
                session._transact(0x9207, params, b'\x02\x00')
        self.assertEqual(camera.commands, [])


def saturation(current=0, **kw):
    return FakeProp(0xD0FF, 1, current, rng=(-9, 9, 1), **kw)


def sharpness_range(current=1, **kw):
    return FakeProp(0xD101, 1, current, rng=(1, 5, 1), **kw)


def wb_shift_ab(current=0xC0, **kw):
    return FakeProp(0xD21C, 2, current, rng=(0x9C, 0xE4, 1), **kw)


def read_only(code=0xD218, current=80):
    return FakeProp(code, 1, current, get_set=0, rng=(-1, 100, 1))


class ReadTests(unittest.TestCase):
    def test_read_all_returns_descriptors_controls_and_advertised_codes(self):
        camera = FakeCamera([contrast(-2), creative_look(0x0006)])
        session, _ = connected(camera)
        snapshot = session.read_all()
        self.assertEqual(camera.commands, [(0x9209, 5, (0,), None)])
        self.assertEqual(snapshot.properties[0xD0FB].current, -2)
        self.assertEqual(snapshot.properties[0xD0FA].current, 0x0006)
        self.assertEqual(snapshot.advertised, frozenset({0xD0FB, 0xD0FA}))

    def test_read_property_uses_get_ext_device_prop_when_advertised(self):
        camera = FakeCamera([contrast(3)])
        session, _ = connected(camera)
        self.assertEqual(session.read_property(0xD0FB).current, 3)
        self.assertEqual([c[:3] for c in camera.commands], [(0x9251, 5, (0xD0FB,))])

    def test_read_property_falls_back_to_the_full_dataset(self):
        camera = FakeCamera([contrast(3)], operations=tuple(op for op in SONY_OPERATIONS if op != 0x9251))
        session, _ = connected(camera)
        self.assertEqual(session.read_property(0xD0FB).current, 3)
        self.assertEqual(camera.opcodes, [0x9209])

    def test_unadvertised_property_is_never_requested(self):
        camera = FakeCamera([contrast(3)])
        session, _ = connected(camera)
        with self.assertRaises(ptp.PropertyUnavailable):
            session.read_property(0xD0FC)
        self.assertEqual(camera.commands, [])

    def test_wrong_record_from_get_ext_device_prop_is_a_protocol_error(self):
        camera = FakeCamera([contrast(3), saturation(1)])
        session, _ = connected(camera)
        camera.mangle[0x9251] = lambda out: [out[0][:12] + saturation(1).record(), out[1]]
        with self.assertRaises(ptp.ProtocolError):
            session.read_property(0xD0FB)
        self.assertFalse(session.usable)

    def test_malformed_dataset_makes_the_session_unusable(self):
        camera = FakeCamera([contrast(3)])
        session, _ = connected(camera)
        camera.mangle[0x9209] = lambda out: [struct.pack('<I', len(out[0]) + 1) + out[0][4:] + b'\x00', out[1]]
        with self.assertRaises(ptp.DatasetError):
            session.read_all()
        with self.assertRaises(ptp.SessionUnusable):
            session.read_all()
        self.assertEqual(camera.opcodes, [0x9209])

    def test_device_busy_on_a_read_is_retried_with_backoff(self):
        camera = FakeCamera([contrast(3)])
        session, clock = connected(camera)
        camera.respond[0x9209] = [0x2019, 0x2019]
        self.assertEqual(session.read_all().properties[0xD0FB].current, 3)
        self.assertEqual(camera.opcodes, [0x9209] * 3)
        self.assertEqual(clock.sleeps, [0.1, 0.2])

    def test_device_busy_retry_is_bounded(self):
        camera = FakeCamera([contrast(3)])
        session, _ = connected(camera, busy_attempts=3)
        camera.respond[0x9209] = [0x2019] * 10
        with self.assertRaises(ptp.DeviceBusy):
            session.read_all()
        self.assertEqual(camera.opcodes, [0x9209] * 3)
        self.assertTrue(session.usable)

    def test_response_codes_map_to_specific_errors(self):
        cases = {0x2006: (ptp.ParameterNotSupported, True), 0x2005: (ptp.OperationNotSupported, False),
                 0x2003: (ptp.SessionLost, False), 0x2004: (ptp.SessionLost, False),
                 0xA101: (ptp.AuthenticationFailed, True), 0xA106: (ptp.SonyResponseError, True),
                 0xA1FF: (ptp.SonyResponseError, True), 0x2002: (ptp.ResponseError, True)}
        for code, (error, still_usable) in cases.items():
            camera = FakeCamera([contrast(3)])
            session, _ = connected(camera)
            camera.respond[0x9209] = [code]
            with self.subTest(hex(code)):
                with self.assertRaises(error) as caught:
                    session.read_all()
                self.assertEqual((caught.exception.code, caught.exception.opcode), (code, 0x9209))
                self.assertEqual(session.usable, still_usable)
        self.assertIn('Camera Status Error', str(ptp.response_error(0xA106, 0x9205)))

    def test_missing_response_marks_the_session_unusable_and_nothing_more_is_sent(self):
        camera = FakeCamera([contrast(3)])
        session, _ = connected(camera)
        camera.silent.add(0x9209)
        with self.assertRaises(ptp.TransportTimeout):
            session.read_all()
        with self.assertRaises(ptp.SessionUnusable):
            session.read_property(0xD0FB)
        self.assertEqual(camera.opcodes, [0x9209])

    def test_response_with_the_wrong_transaction_id_is_a_protocol_error(self):
        camera = FakeCamera([contrast(3)])
        session, _ = connected(camera)
        camera.mangle[0x9209] = lambda out: [out[0], out[1][:8] + struct.pack('<I', 99)]
        with self.assertRaises(ptp.ProtocolError):
            session.read_all()
        self.assertFalse(session.usable)

    def test_reads_need_a_connected_session(self):
        camera = FakeCamera([contrast(3)])
        session, _ = session_for(camera)
        with self.assertRaises(ptp.SessionUnusable):
            session.read_all()
        self.assertEqual(camera.commands, [])


class SetPropertyTests(unittest.TestCase):
    def test_write_is_encoded_by_datatype_and_verified_by_read_back(self):
        camera = FakeCamera([contrast(0), creative_look(0x0001), wb_shift_ab(0xC0)])
        session, _ = connected(camera)
        result = session.set_property(0xD0FB, -2)
        self.assertEqual((result.sent, result.before.current, result.after.current), (True, 0, -2))
        session.set_property(0xD0FA, 0x0101)
        session.set_property(0xD21C, 0xD0)
        self.assertEqual(camera.writes(), [(0xD0FB, b'\xfe'), (0xD0FA, b'\x01\x01'), (0xD21C, b'\xd0')])
        # fresh read, write, read-back for every property
        self.assertEqual(camera.opcodes, [0x9251, 0x9205, 0x9251] * 3)

    def test_value_already_set_sends_no_write(self):
        camera = FakeCamera([contrast(-2)])
        session, _ = connected(camera)
        self.assertFalse(session.set_property(0xD0FB, -2).sent)
        self.assertEqual(camera.opcodes, [0x9251])

    def test_invalid_writes_send_nothing(self):
        cases = {
            'out of range': ([contrast(0)], 0xD0FB, 10, 'outside'),
            'below range': ([sharpness_range(1)], 0xD101, 0, 'outside'),
            'wrong step': ([FakeProp(0xD20F, 4, 5500, rng=(2500, 9900, 100))], 0xD20F, 5550, 'step'),
            'not settable': ([read_only()], 0xD218, 50, 'read-only'),
            'greyed out': ([saturation(0, enabled=0)], 0xD0FF, 2, 'greyed out'),
            'not offered': ([creative_look(0x0001)], 0xD0FA, 0x000C, 'not offered'),
            'not advertised': ([contrast(0)], 0xD0FC, 1, 'did not advertise'),
            'not an integer': ([contrast(0)], 0xD0FB, 1.5, 'integer'),
        }
        for name, (props, code, value, reason) in cases.items():
            camera = FakeCamera(props)
            session, _ = connected(camera)
            with self.subTest(name):
                with self.assertRaisesRegex(ptp.ValidationError, reason) as caught:
                    session.set_property(code, value)
                self.assertEqual(caught.exception.outcome, 'not_sent')
                self.assertNotIn(0x9205, camera.opcodes)

    def test_late_apply_is_polled_until_it_matches(self):
        camera = FakeCamera([contrast(0)])
        camera.delay_writes[0xD0FB] = 2
        session, clock = connected(camera)
        self.assertEqual(session.set_property(0xD0FB, 4).after.current, 4)
        self.assertEqual(camera.opcodes, [0x9251, 0x9205, 0x9251, 0x9251, 0x9251])
        self.assertEqual(clock.sleeps, [0.2, 0.2, 0.2])

    def test_camera_that_ignores_a_write_is_detected_without_resending(self):
        camera = FakeCamera([contrast(0)])
        camera.ignore_writes.add(0xD0FB)
        session, clock = connected(camera, readback_timeout=1.0, readback_interval=0.25)
        with self.assertRaises(ptp.WriteIgnored) as caught:
            session.set_property(0xD0FB, 4)
        self.assertEqual((caught.exception.target, caught.exception.before, caught.exception.after), (4, 0, 0))
        self.assertEqual(caught.exception.outcome, 'not_applied')
        self.assertEqual(camera.opcodes.count(0x9205), 1)
        self.assertEqual(camera.opcodes.count(0x9251), 1 + 4)
        self.assertTrue(session.usable)

    def test_camera_that_coerces_a_write_is_detected(self):
        camera = FakeCamera([contrast(0)])
        camera.coerce[0xD0FB] = 3
        session, _ = connected(camera, readback_timeout=1.0)
        with self.assertRaises(ptp.WriteCoerced) as caught:
            session.set_property(0xD0FB, 4)
        self.assertEqual((caught.exception.before, caught.exception.after), (0, 3))
        self.assertEqual(camera.opcodes.count(0x9205), 1)

    def test_device_busy_write_is_re_read_before_it_is_sent_again(self):
        camera = FakeCamera([contrast(0)])
        camera.respond[0x9205] = [0x2019]
        session, clock = connected(camera)
        self.assertTrue(session.set_property(0xD0FB, 4).sent)
        self.assertEqual(camera.opcodes, [0x9251, 0x9205, 0x9251, 0x9205, 0x9251])
        self.assertEqual(clock.sleeps[0], 0.1)

    def test_device_busy_write_retry_is_bounded(self):
        camera = FakeCamera([contrast(0)])
        camera.respond[0x9205] = [0x2019] * 10
        session, _ = connected(camera, busy_attempts=3)
        with self.assertRaises(ptp.DeviceBusy) as caught:
            session.set_property(0xD0FB, 4)
        self.assertEqual(camera.opcodes.count(0x9205), 3)
        self.assertEqual(caught.exception.outcome, 'rejected')

    def test_rejected_write_is_reported_and_not_retried(self):
        camera = FakeCamera([contrast(0)])
        camera.respond[0x9205] = [0x2006]
        session, _ = connected(camera)
        with self.assertRaises(ptp.ParameterNotSupported):
            session.set_property(0xD0FB, 4)
        self.assertEqual(camera.opcodes, [0x9251, 0x9205])

    def test_write_with_no_answer_is_unknown_and_never_resent(self):
        camera = FakeCamera([contrast(0)])
        camera.silent.add(0x9205)
        session, _ = connected(camera)
        with self.assertRaises(ptp.TransportTimeout) as caught:
            session.set_property(0xD0FB, 4)
        self.assertEqual(caught.exception.outcome, 'unknown')
        with self.assertRaises(ptp.SessionUnusable):
            session.set_property(0xD0FB, 4)
        self.assertEqual(camera.opcodes, [0x9251, 0x9205])

    def test_set_property_never_uses_control_device(self):
        camera = FakeCamera([contrast(0), creative_look(0x0001)])
        session, _ = connected(camera)
        session.set_property(0xD0FA, 0x0006)
        session.set_property(0xD0FB, 1)
        self.assertNotIn(0x9207, camera.opcodes)


# ---------------------------------------------------------------- pyusb transport, simulated endpoints
import usb.core  # noqa: E402  (the root conftest already blocks usb.core.find)


class FakeEndpoint:
    def __init__(self, address, attributes=2, max_packet=512, reads=()):
        self.bEndpointAddress, self.bmAttributes, self.wMaxPacketSize = address, attributes, max_packet
        self.reads, self.written, self.read_sizes, self.short_by = list(reads), [], [], 0

    def write(self, data, timeout):
        assert isinstance(timeout, int) and timeout > 0
        if isinstance(self.reads, list) and self.reads and isinstance(self.reads[0], usb.core.USBError):
            raise self.reads.pop(0)
        self.written.append(bytes(data))
        return len(data) - self.short_by

    def read(self, size, timeout):
        assert isinstance(timeout, int) and timeout > 0
        self.read_sizes.append(size)
        item = self.reads.pop(0)
        if isinstance(item, Exception):
            raise item
        assert len(item) <= size, 'device sent more than the host asked for'
        return bytearray(item)


class FakeInterface(list):
    def __init__(self, endpoints, kind=(6, 1, 1), number=0):
        super().__init__(endpoints)
        self.bInterfaceClass, self.bInterfaceSubClass, self.bInterfaceProtocol = kind
        self.bInterfaceNumber = number


class FakeDevice(list):
    """A pyusb-like device: iterating yields configurations, which yield interfaces."""

    def __init__(self, interfaces, vendor=0x054C, product=0x1234):
        super().__init__([list(interfaces)])
        self.idVendor, self.idProduct = vendor, product


def ptp_interface(**kw):
    return FakeInterface([FakeEndpoint(0x01), FakeEndpoint(0x81), FakeEndpoint(0x82, attributes=3, max_packet=8)], **kw)


def transport_with(reads=(), max_packet=512):
    out, inp = FakeEndpoint(0x01, max_packet=max_packet), FakeEndpoint(0x81, max_packet=max_packet, reads=reads)
    released = []
    clock = FakeClock()
    transport = ptp.PyUsbTransport(FakeDevice([]), 0, out, inp, clock=clock.time,
                                   release=lambda device, number: released.append(number))
    return transport, out, inp, released


class PyUsbTransportTests(unittest.TestCase):
    def test_camera_is_matched_by_vendor_and_still_image_interface_not_product_id(self):
        camera = FakeDevice([ptp_interface(number=0)], product=0x7777)
        others = [FakeDevice([FakeInterface([FakeEndpoint(1), FakeEndpoint(0x81)], kind=(8, 6, 0x50))]),
                  FakeDevice([ptp_interface()], vendor=0x04A9)]
        device, interface, out, inp = ptp.select_camera(others + [camera])
        self.assertIs(device, camera)
        self.assertEqual((interface.bInterfaceNumber, out.bEndpointAddress, inp.bEndpointAddress), (0, 0x01, 0x81))

    def test_mass_storage_only_body_is_not_a_pc_remote_camera(self):
        msc = FakeDevice([FakeInterface([FakeEndpoint(1), FakeEndpoint(0x81)], kind=(8, 6, 0x50))], product=0x0E8A)
        with self.assertRaisesRegex(ptp.ConnectError, 'PC Remote'):
            ptp.select_camera([msc])

    def test_more_than_one_camera_is_refused(self):
        with self.assertRaisesRegex(ptp.ConnectError, 'one'):
            ptp.select_camera([FakeDevice([ptp_interface()]), FakeDevice([ptp_interface()], product=0x0001)])

    def test_still_image_interface_without_bulk_pair_is_refused(self):
        broken = FakeDevice([FakeInterface([FakeEndpoint(0x81), FakeEndpoint(0x82, attributes=3)])])
        with self.assertRaisesRegex(ptp.ConnectError, 'endpoint'):
            ptp.select_camera([broken])

    def test_send_adds_a_zero_length_packet_only_on_exact_multiples(self):
        transport, out, _, _ = transport_with()
        transport.send(bytes(512), 2.0)
        transport.send(bytes(100), 2.0)
        self.assertEqual([len(w) for w in out.written], [512, 0, 100])

    def test_short_write_and_usb_errors(self):
        transport, out, _, _ = transport_with()
        out.short_by = 1
        with self.assertRaises(ptp.TransportError):
            transport.send(bytes(20), 1.0)
        transport, out, _, _ = transport_with()
        out.reads = [usb.core.USBTimeoutError('timeout', -7, 60)]
        with self.assertRaises(ptp.TransportTimeout):
            transport.send(bytes(20), 1.0)
        transport, out, _, _ = transport_with()
        out.reads = [usb.core.USBError('Pipe error', -9, 32)]
        with self.assertRaises(ptp.TransportError):
            transport.send(bytes(20), 1.0)

    def test_receive_reassembles_a_multi_packet_container(self):
        container = struct.pack('<IHHI', 1036, 2, 0x9209, 5) + bytes(range(256)) * 4
        transport, _, inp, _ = transport_with([container[:512], container[512:1024], container[1024:]])
        self.assertEqual(transport.receive(2.0), container)
        self.assertTrue(all(size % 512 == 0 for size in inp.read_sizes))

    def test_receive_skips_a_pending_zero_length_packet(self):
        response = struct.pack('<IHHI', 12, 3, 0x2001, 5)
        transport, _, _, _ = transport_with([b'', response])
        self.assertEqual(transport.receive(2.0), response)

    def test_receive_fails_closed_on_bad_framing(self):
        header = struct.pack('<IHHI', 600, 2, 0x9209, 5)
        cases = {
            'ends early': [header + bytes(500), b''],
            'more than declared': [struct.pack('<IHHI', 14, 3, 0x2001, 5) + bytes(4)],
            'short header': [b'\x0c\x00'],
            'absurd length': [struct.pack('<IHHI', 0x7FFFFFFF, 2, 0x9209, 5)],
        }
        for name, reads in cases.items():
            transport, _, _, _ = transport_with(reads)
            with self.subTest(name), self.assertRaises(ptp.ProtocolError):
                transport.receive(2.0)

    def test_receive_timeout(self):
        transport, _, _, _ = transport_with([usb.core.USBTimeoutError('timeout', -7, 60)])
        with self.assertRaises(ptp.TransportTimeout):
            transport.receive(1.0)

    def test_close_releases_the_interface_once(self):
        transport, _, _, released = transport_with()
        transport.close()
        transport.close()
        self.assertEqual(released, [0])

    def test_open_claims_the_selected_interface(self):
        claimed = []
        transport = ptp.PyUsbTransport.open(devices=[FakeDevice([ptp_interface(number=2)])],
                                            claim=lambda device, number: claimed.append(number),
                                            release=lambda device, number: None)
        self.assertEqual(claimed, [2])
        transport.close()

    def test_open_reports_a_busy_interface(self):
        def busy(device, number):
            raise usb.core.USBError('Access denied (insufficient permissions)', -3, 13)
        with self.assertRaisesRegex(ptp.InterfaceBusy, 'another process'):
            ptp.PyUsbTransport.open(devices=[FakeDevice([ptp_interface()])], claim=busy,
                                    release=lambda device, number: None)


class Completed:
    def __init__(self, returncode=0, stdout=''):
        self.returncode, self.stdout, self.stderr = returncode, stdout, ''


class PtpcameradTests(unittest.TestCase):
    """macOS: stop the user's ptpcamerad only with consent, then claim with bounded retries."""

    def setUp(self):
        self.commands, self.sleeps = [], []
        self.running = {'ptpcamerad'}

    def run_command(self, command, **kwargs):
        self.commands.append(command)
        if command[0] == '/usr/bin/pgrep':
            return Completed(0 if command[-1] in self.running else 1, '123\n' if command[-1] in self.running else '')
        return Completed(0)

    def release(self, opener, **kw):
        kw.setdefault('consent', True)
        return ptp.claim_after_stopping_ptpcamerad(opener, run=self.run_command, sleep=self.sleeps.append,
                                                   platform='darwin', uid=501, attempts=3, delay=0.2, **kw)

    def test_nothing_happens_without_explicit_consent(self):
        for consent in (False, None, 'yes', 1):
            with self.subTest(consent), self.assertRaises(ptp.ConsentRequired):
                self.release(lambda: self.fail('must not open'), consent=consent)
        self.assertEqual(self.commands, [])

    def test_stops_ptpcamerad_for_this_user_without_sudo_then_claims(self):
        attempts = []

        def opener():
            attempts.append(1)
            if len(attempts) < 2:
                raise ptp.InterfaceBusy('held')
            return 'transport'
        self.assertEqual(self.release(opener), 'transport')
        kills = [c for c in self.commands if c[0] == '/usr/bin/pkill']
        self.assertEqual(kills, [['/usr/bin/pkill', '-9', '-U', '501', '-x', 'ptpcamerad']] * 2)
        self.assertFalse(any('sudo' in part for command in self.commands for part in command))
        self.assertEqual(self.sleeps, [0.2])

    def test_reports_which_process_still_holds_the_camera(self):
        self.running = {'ptpcamerad', 'Image Capture'}

        def opener():
            raise ptp.InterfaceBusy('held')
        with self.assertRaisesRegex(ptp.InterfaceBusy, 'Image Capture') as caught:
            self.release(opener)
        self.assertIn('ptpcamerad', str(caught.exception))
        self.assertEqual(len([c for c in self.commands if c[0] == '/usr/bin/pkill']), 3)

    def test_reports_an_unknown_holder(self):
        self.running = set()
        with self.assertRaisesRegex(ptp.InterfaceBusy, 'no known camera application'):
            self.release(lambda: (_ for _ in ()).throw(ptp.InterfaceBusy('held')))

    def test_other_open_failures_are_not_retried(self):
        calls = []

        def opener():
            calls.append(1)
            raise ptp.ConnectError('No Sony camera in PC Remote mode')
        with self.assertRaises(ptp.ConnectError):
            self.release(opener)
        self.assertEqual(len(calls), 1)

    def test_failed_pkill_stops(self):
        def run(command, **kwargs):
            self.commands.append(command)
            return Completed(3)
        with self.assertRaisesRegex(ptp.PtpError, 'pkill'):
            ptp.claim_after_stopping_ptpcamerad(lambda: 'transport', consent=True, run=run, sleep=self.sleeps.append,
                                                platform='darwin', uid=501)

    def test_macos_only(self):
        with self.assertRaises(ptp.PtpError):
            ptp.claim_after_stopping_ptpcamerad(lambda: 'transport', consent=True, run=self.run_command,
                                                platform='win32')
        self.assertEqual(self.commands, [])


class SessionEdgeTests(unittest.TestCase):
    def test_accepted_write_that_cannot_be_read_back_is_unknown_and_stops_the_session(self):
        camera = FakeCamera([contrast(0)])
        camera.after_write.append(lambda cam, code, value: cam.respond.__setitem__(0x9251, [0x2019] * 10))
        session, _ = connected(camera, busy_attempts=3)
        with self.assertRaises(ptp.WriteUnverified) as caught:
            session.set_property(0xD0FB, 4)
        self.assertEqual(caught.exception.outcome, 'unknown')
        self.assertIsInstance(caught.exception.__cause__, ptp.DeviceBusy)
        self.assertFalse(session.usable)
        with self.assertRaises(ptp.SessionUnusable):
            session.set_property(0xD0FB, 4)
        self.assertEqual(camera.opcodes.count(0x9205), 1)

    def test_close_is_idempotent(self):
        camera = FakeCamera([contrast(0)])
        closes = []
        camera.close = lambda: closes.append(1)
        session, _ = connected(camera)
        session.close()
        session.close()
        self.assertEqual((camera.opcodes, closes), ([0x1003], [1]))

    def test_failed_connect_reports_its_own_error_even_if_release_fails(self):
        camera = FakeCamera([contrast(0)], model='ILCE-7M4')

        def broken_release():
            raise RuntimeError('release failed')
        camera.close = broken_release
        session, _ = session_for(camera)
        with self.assertRaises(ptp.ConnectError):
            session.connect()

    def test_retry_bounds_must_allow_at_least_one_attempt(self):
        for kw in (dict(busy_attempts=0), dict(ext_info_attempts=0), dict(readback_timeout=0),
                   dict(readback_interval=0)):
            with self.subTest(kw), self.assertRaises(ValueError):
                ptp.RemoteSession(FakeCamera(), **kw)


class WriteOutcomeTests(unittest.TestCase):
    """What set_property reports when the fresh read before a write fails."""

    def test_a_failed_read_before_any_write_reports_that_nothing_was_sent(self):
        for code, error in ((0x2019, ptp.DeviceBusy), (0x2006, ptp.ParameterNotSupported)):
            with self.subTest(hex(code)):
                camera = FakeCamera([contrast(0)])
                session, _ = connected(camera)
                camera.respond[0x9251] = [code] * 5
                with self.assertRaises(error) as raised:
                    session.set_property(0xD0FB, -2)
                self.assertEqual((raised.exception.outcome, camera.writes()), ('not_sent', []))

    def test_a_failed_reread_after_a_busy_write_reports_a_refused_write(self):
        camera = FakeCamera([contrast(0)])
        session, _ = connected(camera)
        camera.respond[0x9205] = [0x2019]
        session._sleep = lambda seconds: camera.respond.__setitem__(0x9251, [0x2006])
        with self.assertRaises(ptp.ParameterNotSupported) as raised:
            session.set_property(0xD0FB, -2)
        self.assertEqual((raised.exception.outcome, len(camera.writes())), ('rejected', 1))

    def test_a_busy_write_that_the_reread_finds_applied_counts_as_sent(self):
        camera = FakeCamera([contrast(0)])
        session, _ = connected(camera)
        camera.respond[0x9205] = [0x2019]
        session._sleep = lambda seconds: setattr(camera.props[0xD0FB], 'current', -2)
        result = session.set_property(0xD0FB, -2)
        self.assertEqual((result.sent, result.after.current, len(camera.writes())), (True, -2, 1))


class SessionExitTests(unittest.TestCase):
    """Leaving `with RemoteSession(...)` must never replace the outcome the caller needs to see."""

    def unplugged(self):
        camera = FakeCamera([contrast(0)])
        def release():
            raise OSError(19, 'No such device')
        camera.close = release
        return ptp.RemoteSession(camera, clock=FakeClock().time, sleep=lambda seconds: None)

    def test_a_release_error_never_hides_the_error_being_raised(self):
        with self.assertRaisesRegex(RuntimeError, 'the real failure'):
            with self.unplugged():
                raise RuntimeError('the real failure')

    def test_a_release_error_after_a_finished_session_is_logged_not_raised(self):
        import contextlib, io
        log = io.StringIO()
        with contextlib.redirect_stderr(log):
            with self.unplugged() as camera:
                snapshot = camera.read_all()
        self.assertIn(0xD0FB, snapshot.properties)
        self.assertIn('No such device', log.getvalue())
