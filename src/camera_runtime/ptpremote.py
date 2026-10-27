"""Sony "PC Remote" USB PTP session for camera settings (experimental recipe writer).

Implements the subset of Sony's Camera Control PTP 3 Reference that a settings
writer needs: GetDeviceInfo, the SDIO connection handshake, reading property
descriptors (0x9209/0x9251) and writing one property (0x9205) with read-back.
Nothing here has been verified on a real ILCE-7CM2; every step fails closed.

Rules enforced here, not by callers:
- Every command passes one choke point (`check_operation`): the opcode must be on
  ALLOWED_OPERATIONS and advertised by the device's GetDeviceInfo. Sony bodies
  stall the bulk pipe on operations they do not implement.
- 0x9207 (ControlDevice) only ever for control 0xD306; this module never sends it.
- A write whose outcome is unknown (timeout, disconnect, malformed reply) marks the
  session unusable; nothing is sent afterwards. A write is never re-sent without a
  fresh read of the property first.
- Importing this module never touches USB; pyusb loads only in PyUsbTransport.
"""
import os
import struct
import subprocess
import sys
import time
from dataclasses import dataclass
from typing import Protocol

# Container types (PIMA 15740 USB still-image class).
COMMAND, DATA, RESPONSE, EVENT = 1, 2, 3, 4
HEADER = struct.Struct('<IHHI')
MAX_PARAMS = 5

# Operations.
GET_DEVICE_INFO = 0x1001
OPEN_SESSION = 0x1002
CLOSE_SESSION = 0x1003
SDIO_CONNECT = 0x9201
SDIO_GET_EXT_DEVICE_INFO = 0x9202
SDIO_SET_EXT_DEVICE_PROP_VALUE = 0x9205
SDIO_CONTROL_DEVICE = 0x9207
SDIO_GET_ALL_EXT_DEVICE_PROP_INFO = 0x9209
SDIO_GET_VENDOR_CODE_VERSION = 0x9216
SDIO_GET_EXT_DEVICE_PROP = 0x9251
ALLOWED_OPERATIONS = frozenset({
    GET_DEVICE_INFO, OPEN_SESSION, CLOSE_SESSION, SDIO_CONNECT, SDIO_GET_EXT_DEVICE_INFO,
    SDIO_SET_EXT_DEVICE_PROP_VALUE, SDIO_CONTROL_DEVICE, SDIO_GET_ALL_EXT_DEVICE_PROP_INFO,
    SDIO_GET_VENDOR_CODE_VERSION, SDIO_GET_EXT_DEVICE_PROP})
RESET_CREATIVE_LOOK = 0xD306  # the only control code 0x9207 may carry
# Without these the body is not in PC Remote mode (or is not a PC Remote body).
REQUIRED_OPERATIONS = frozenset({OPEN_SESSION, CLOSE_SESSION, SDIO_CONNECT, SDIO_GET_EXT_DEVICE_INFO,
                                 SDIO_SET_EXT_DEVICE_PROP_VALUE, SDIO_GET_ALL_EXT_DEVICE_PROP_INFO})
MUTATING_OPERATIONS = frozenset({SDIO_SET_EXT_DEVICE_PROP_VALUE, SDIO_CONTROL_DEVICE})
INITIATOR_VERSION = 0x012C  # 3.00; the camera must answer the same extension version
SESSION_ID = 1
MANUFACTURER = 'Sony Corporation'
MODEL = 'ILCE-7CM2'

# Response codes (PIMA 15740 and Sony p.85).
OK = 0x2001
RESPONSE_NAMES = {
    0x2001: 'OK', 0x2002: 'General Error', 0x2003: 'Session Not Open', 0x2004: 'Invalid TransactionID',
    0x2005: 'Operation Not Supported', 0x2006: 'Parameter Not Supported', 0x2019: 'Device Busy',
    0x201E: 'Session Already Open', 0xA101: 'Authentication Failed', 0xA102: 'Password Length Over Max',
    0xA103: 'Password Includes Invalid Character', 0xA104: 'Feature Version Invalid Value',
    0xA105: 'Temporary Storage Full', 0xA106: 'Camera Status Error'}


class PtpError(RuntimeError):
    """Base class. `outcome` tells a caller what is known about a write in flight."""
    outcome = 'unknown'


class ProtocolError(PtpError):
    """A reply does not match the protocol; the session cannot continue."""


class DatasetError(ProtocolError):
    """A dataset did not parse exactly to its end; nothing parsed from it is trusted."""


class OperationRefused(PtpError):
    """The choke point refused a command; nothing was sent."""
    outcome = 'not_sent'


class SessionUnusable(PtpError):
    """An earlier failure left the session in an unknown state; nothing was sent."""
    outcome = 'not_sent'


class ConnectError(PtpError):
    """The camera is not a usable PC Remote ILCE-7CM2; no setting was written."""
    outcome = 'not_sent'


class InterfaceBusy(ConnectError):
    """Another process holds the camera's still-image interface; nothing was sent."""


class ConsentRequired(PtpError):
    """A host-changing helper was called without the user's explicit consent; nothing ran."""
    outcome = 'not_sent'


class PropertyUnavailable(PtpError):
    """The camera did not advertise (or did not report) this property; nothing was sent."""
    outcome = 'not_sent'


class ValidationError(PtpError):
    """A freshly read descriptor does not allow the value; nothing was written."""
    outcome = 'not_sent'

    def __init__(self, code, value, reason):
        self.code, self.value, self.reason = code, value, reason
        super().__init__('Not writing 0x%04X = %r: %s' % (code, value, reason))


class WriteNotApplied(PtpError):
    """The camera answered OK but the read-back never showed the target value."""
    outcome = 'not_applied'

    def __init__(self, code, target, before, after):
        self.code, self.target, self.before, self.after = code, target, before, after
        super().__init__('Camera accepted 0x%04X = %r but reads back %r (was %r)' % (code, target, after, before))


class WriteIgnored(WriteNotApplied):
    """The value never changed."""


class WriteCoerced(WriteNotApplied):
    """The value changed, but not to the target."""


class WriteUnverified(PtpError):
    """The camera accepted a write that could not be read back; the outcome is unknown."""

    def __init__(self, code, target, before):
        self.code, self.target, self.before = code, target, before
        super().__init__('Camera accepted 0x%04X = %r (was %r) but it could not be read back' % (code, target, before))


class TransportError(PtpError):
    """USB I/O failed; whatever was in flight has an unknown outcome."""


class TransportTimeout(TransportError):
    """USB I/O did not complete in time; whatever was in flight has an unknown outcome."""


class ResponseError(PtpError):
    """The camera answered with a response code other than OK; it did not perform the operation."""
    outcome = 'rejected'

    def __init__(self, code, opcode):
        self.code, self.opcode = code, opcode
        super().__init__('Camera answered 0x%04X (%s) to operation 0x%04X' % (
            code, RESPONSE_NAMES.get(code, 'unknown response'), opcode))


class DeviceBusy(ResponseError):
    """0x2019: retried with bounded back-off; a write is re-read before it is sent again."""


class ParameterNotSupported(ResponseError):
    """0x2006: the camera does not support this property or value now."""


class OperationNotSupported(ResponseError):
    """0x2005: the session stops."""


class SessionLost(ResponseError):
    """0x2003/0x2004: the camera lost the session or transaction sequence; the session stops."""


class SessionAlreadyOpen(ResponseError):
    """0x201E: handled once during connect by closing and reopening."""


class SonyResponseError(ResponseError):
    """A Sony vendor response 0xA1xx."""


class AuthenticationFailed(SonyResponseError):
    """0xA101: the camera rejected the initiator version or authentication."""


_RESPONSE_ERRORS = {0x2019: DeviceBusy, 0x2006: ParameterNotSupported, 0x2005: OperationNotSupported,
                    0x2003: SessionLost, 0x2004: SessionLost, 0x201E: SessionAlreadyOpen,
                    0xA101: AuthenticationFailed}
_FATAL_RESPONSES = (OperationNotSupported, SessionLost)


def response_error(code, opcode):
    """Map a non-OK response code to its exception (not raised here)."""
    cls = _RESPONSE_ERRORS.get(code) or (SonyResponseError if 0xA100 <= code <= 0xA1FF else ResponseError)
    return cls(code, opcode)


# Datatypes (PIMA 15740 plus Sony's STR code) and descriptor forms (p.121-122).
INT8, UINT8, INT16, UINT16, INT32, UINT32, INT64, UINT64, INT128, UINT128 = range(1, 11)
STR = 0xFFFF
ARRAY = 0x4000  # ARRAY | scalar datatype: u32 count, then elements
FORM_NONE, FORM_RANGE, FORM_ENUM = 0, 1, 2
_INTEGERS = {INT8: struct.Struct('<b'), UINT8: struct.Struct('<B'), INT16: struct.Struct('<h'),
             UINT16: struct.Struct('<H'), INT32: struct.Struct('<i'), UINT32: struct.Struct('<I'),
             INT64: struct.Struct('<q'), UINT64: struct.Struct('<Q')}
_WIDE = {INT128: True, UINT128: False}  # 16-byte integers: signed?
_MIN_RECORD = 9  # smallest property record: 6-byte head, two 1-byte values, form flag
_MAX_RECORDS = 65536


class _Reader:
    """Bounds-checked little-endian reader; every overrun is a DatasetError."""

    def __init__(self, data):
        self.data, self.offset = bytes(data), 0

    @property
    def remaining(self):
        return len(self.data) - self.offset

    def take(self, size):
        if size < 0 or size > self.remaining:
            raise DatasetError('Dataset truncated at byte %d (needs %d more, %d left)' %
                               (self.offset, size, self.remaining))
        chunk = self.data[self.offset:self.offset + size]
        self.offset += size
        return chunk

    def unpack(self, layout):
        return layout.unpack(self.take(layout.size))[0]

    def u8(self):
        return self.take(1)[0]

    def u16(self):
        return self.unpack(_INTEGERS[UINT16])

    def u32(self):
        return self.unpack(_INTEGERS[UINT32])

    def u64(self):
        return self.unpack(_INTEGERS[UINT64])

    def codes(self):
        count = self.u32()
        if 2 * count > self.remaining:
            raise DatasetError('Code array of %d entries exceeds the dataset' % count)
        return frozenset(self.u16() for _ in range(count))

    def finish(self, what):
        if self.remaining:
            raise DatasetError('%d unexpected bytes after %s' % (self.remaining, what))

    def string(self):
        count = self.u8()
        if count == 0:
            return ''
        units = self.take(2 * count)
        if units[-2:] != b'\x00\x00':
            raise DatasetError('PTP string at byte %d is not NUL-terminated' % (self.offset - 2 * count - 1))
        try:
            return units[:-2].decode('utf-16-le')
        except UnicodeDecodeError as exc:
            raise DatasetError('PTP string is not valid UTF-16') from exc

    def scalar(self, datatype):
        if datatype in _INTEGERS:
            return self.unpack(_INTEGERS[datatype])
        if datatype in _WIDE:
            return int.from_bytes(self.take(16), 'little', signed=_WIDE[datatype])
        raise DatasetError('Unknown datatype 0x%04X' % datatype)

    def value(self, datatype):
        if datatype == STR:
            return self.string()
        if datatype & ARRAY and (datatype & ~ARRAY) in _INTEGERS.keys() | _WIDE.keys():
            count = self.u32()
            if count > self.remaining:
                raise DatasetError('Array of %d elements exceeds the dataset' % count)
            return tuple(self.scalar(datatype & ~ARRAY) for _ in range(count))
        return self.scalar(datatype)

    def values(self, datatype):
        count = self.u16()
        if count > self.remaining:
            raise DatasetError('Enumeration of %d values exceeds the dataset' % count)
        return tuple(self.value(datatype) for _ in range(count))


def _element_type(datatype):
    return datatype & ~ARRAY if datatype & ARRAY and datatype != STR else datatype


@dataclass(frozen=True)
class PropertyDescriptor:
    """One SDIDevicePropInfo dataset (p.121-122), as the camera reported it.

    enum_set / enum_get_set are Sony's "Set" and "Get/Set" lists in wire order.
    Sources disagree on which one is authoritative for writing (Sony names the
    first "Set"; libgphoto2 and mikefsq/ptp prefer the second), so a value is
    settable only when it appears in both.
    """
    code: int
    datatype: int
    get_set: int
    enabled: int
    default: object
    current: object
    form: int
    minimum: object = None
    maximum: object = None
    step: object = None
    enum_set: tuple = ()
    enum_get_set: tuple = ()

    @property
    def settable_values(self):
        return tuple(v for v in self.enum_set if v in self.enum_get_set)

    def refusal(self, value, *, require_enabled=True):
        """Why `value` cannot be written now, or None. Pure; nothing is sent.

        require_enabled=False skips only the greyed-out check, for a write planned
        after a selector change that the camera has not made yet.
        """
        name = '0x%04X' % self.code
        if self.datatype not in _INTEGERS:
            return '%s has datatype 0x%04X, which this tool does not write' % (name, self.datatype)
        if type(value) is not int:
            return '%s needs an integer value, not %r' % (name, value)
        if self.get_set != 1:
            return '%s is read-only on this camera' % name
        if require_enabled and self.enabled != 1:
            state = {0: 'greyed out', 2: 'display-only'}.get(self.enabled, 'in unknown state %d' % self.enabled)
            return '%s is %s on the camera right now' % (name, state)
        layout = _INTEGERS[self.datatype]
        try:
            layout.pack(value)
        except struct.error:
            return '%s value %d does not fit datatype 0x%04X' % (name, value, self.datatype)
        if self.form == FORM_RANGE:
            if not isinstance(self.step, int) or self.step <= 0:
                return '%s: the camera reports an invalid step %r' % (name, self.step)
            if not self.minimum <= value <= self.maximum:
                return '%s value %d is outside the camera range %d..%d' % (name, value, self.minimum, self.maximum)
            if (value - self.minimum) % self.step:
                return '%s value %d is not on the camera step %d from %d' % (name, value, self.step, self.minimum)
            return None
        if self.form == FORM_ENUM:
            if value not in self.settable_values:
                return '%s value 0x%X is not offered by the camera (settable: %s)' % (
                    name, value, ', '.join('0x%X' % v for v in self.settable_values) or 'none')
            return None
        return '%s: the camera reports no range or list for it' % name


@dataclass(frozen=True)
class ControlDescriptor:
    """A control record inside 0x9209 (p.680; sarnau's ILCE-7RM5 capture): 11 bytes, no form payload."""
    code: int
    datatype: int
    control_type: int
    enabled: int
    form: int


def _read_property(reader):
    code, datatype = reader.u16(), reader.u16()
    get_set, enabled = reader.u8(), reader.u8()
    default, current = reader.value(datatype), reader.value(datatype)
    form = reader.u8()
    extra = {}
    if form == FORM_RANGE:
        element = _element_type(datatype)
        extra = dict(minimum=reader.value(element), maximum=reader.value(element), step=reader.value(element))
    elif form == FORM_ENUM:
        element = _element_type(datatype)
        extra = dict(enum_set=reader.values(element), enum_get_set=reader.values(element))
    elif form != FORM_NONE:
        raise DatasetError('Property 0x%04X has unknown form flag %d' % (code, form))
    return PropertyDescriptor(code, datatype, get_set, enabled, default, current, form, **extra)


def _read_control(reader):
    code, datatype = reader.u16(), reader.u16()
    control_type, enabled = reader.u8(), reader.u8()
    reader.take(4)
    return ControlDescriptor(code, datatype, control_type, enabled, reader.u8())


def parse_all_properties(data, control_codes=frozenset(), property_codes=frozenset()):
    """Parse a 0x9209 SDIDevicePropInfo Dataset Array exactly to its end.

    Records whose code the camera advertised as a control use the control shape.
    Returns ({code: PropertyDescriptor}, {code: ControlDescriptor}).
    """
    overlap = set(control_codes) & set(property_codes)
    if overlap:
        raise DatasetError('Codes advertised as both property and control: %s' %
                           ', '.join('0x%04X' % c for c in sorted(overlap)))
    reader = _Reader(data)
    count = reader.u64()
    if count > min(_MAX_RECORDS, reader.remaining // _MIN_RECORD):
        raise DatasetError('Dataset claims %d records in %d bytes' % (count, reader.remaining))
    properties, controls = {}, {}
    for _ in range(count):
        code = struct.unpack_from('<H', reader.data, reader.offset)[0] if reader.remaining >= 2 else None
        row = _read_control(reader) if code in control_codes else _read_property(reader)
        if row.code in properties or row.code in controls:
            raise DatasetError('Property 0x%04X appears twice' % row.code)
        (controls if code in control_codes else properties)[row.code] = row
    if reader.remaining:
        raise DatasetError('%d unexpected bytes after %d records' % (reader.remaining, count))
    return properties, controls


def parse_property(data):
    """Parse one SDIDevicePropInfo dataset (0x9251 data phase) exactly to its end."""
    reader = _Reader(data)
    row = _read_property(reader)
    if reader.remaining:
        raise DatasetError('%d unexpected bytes after property 0x%04X' % (reader.remaining, row.code))
    return row


@dataclass(frozen=True)
class Container:
    kind: int
    code: int
    tid: int
    payload: bytes = b''

    @property
    def params(self):
        return struct.unpack('<%dI' % (len(self.payload) // 4), self.payload)


def pack_container(kind, code, tid, payload=b''):
    return HEADER.pack(HEADER.size + len(payload), kind, code, tid) + bytes(payload)


def pack_command(opcode, tid, params=()):
    if len(params) > MAX_PARAMS:
        raise ValueError('A PTP command carries at most %d parameters' % MAX_PARAMS)
    return pack_container(COMMAND, opcode, tid, struct.pack('<%dI' % len(params), *params))


def unpack_container(data):
    data = bytes(data)
    if len(data) < HEADER.size:
        raise ProtocolError('PTP container shorter than its 12-byte header (%d bytes)' % len(data))
    length, kind, code, tid = HEADER.unpack_from(data)
    if length != len(data):
        raise ProtocolError('PTP container declares %d bytes but %d arrived' % (length, len(data)))
    if kind not in (COMMAND, DATA, RESPONSE, EVENT):
        raise ProtocolError('Unknown PTP container type %d' % kind)
    payload = data[HEADER.size:]
    if kind in (COMMAND, RESPONSE, EVENT) and (len(payload) % 4 or len(payload) > 4 * MAX_PARAMS):
        raise ProtocolError('PTP container type %d has a malformed parameter block (%d bytes)' % (kind, len(payload)))
    return Container(kind, code, tid, payload)


def check_operation(opcode, params, operations, controls):
    """The single gate every command passes. Raises OperationRefused; sends nothing.

    `operations`/`controls` are what the device advertised (GetDeviceInfo and
    GetExtDeviceInfo); None means not yet known.
    """
    if opcode not in ALLOWED_OPERATIONS:
        raise OperationRefused('Operation 0x%04X is not on the PC Remote allow-list' % opcode)
    if operations is None:
        if opcode != GET_DEVICE_INFO:
            raise OperationRefused('Operation 0x%04X refused before GetDeviceInfo is known' % opcode)
        return
    if opcode not in operations:
        raise OperationRefused('The camera did not advertise operation 0x%04X' % opcode)
    if opcode == SDIO_CONTROL_DEVICE:
        if not params or params[0] != RESET_CREATIVE_LOOK:
            raise OperationRefused('ControlDevice 0x9207 is permitted only for control 0xD306')
        if not controls or RESET_CREATIVE_LOOK not in controls:
            raise OperationRefused('The camera did not advertise control 0xD306')


@dataclass(frozen=True)
class DeviceInfo:
    """PIMA 15740 DeviceInfo. The serial number is parsed for framing and never kept."""
    standard_version: int
    vendor_extension_id: int
    vendor_extension_version: int
    vendor_extension_desc: str
    functional_mode: int
    operations: frozenset
    events: frozenset
    device_properties: frozenset
    capture_formats: frozenset
    image_formats: frozenset
    manufacturer: str
    model: str
    device_version: str


def parse_device_info(data):
    reader = _Reader(data)
    head = (reader.u16(), reader.u32(), reader.u16(), reader.string(), reader.u16())
    lists = tuple(reader.codes() for _ in range(5))
    strings = (reader.string(), reader.string(), reader.string())
    reader.string()  # SerialNumber
    reader.finish('DeviceInfo')
    return DeviceInfo(*head, *lists, *strings)


@dataclass(frozen=True)
class ExtDeviceInfo:
    """SDIExtDeviceInfo (p.118): what this body offers over PC Remote."""
    version: int
    properties: frozenset
    controls: frozenset
    vendor_code_version: object = None


def parse_ext_device_info(data, vendor_code_version=None):
    reader = _Reader(data)
    version = reader.u16()
    properties, controls = reader.codes(), reader.codes()
    reader.finish('SDIExtDeviceInfo')
    return ExtDeviceInfo(version, properties, controls, vendor_code_version)


@dataclass(frozen=True)
class ConnectInfo:
    device: DeviceInfo
    ext: ExtDeviceInfo


@dataclass(frozen=True)
class Reply:
    params: tuple
    data: object  # bytes, or None when the camera sent no data phase


@dataclass(frozen=True)
class Snapshot:
    """One 0x9209 read: {code: PropertyDescriptor}, {code: ControlDescriptor}, advertised property codes."""
    properties: dict
    controls: dict
    advertised: frozenset


@dataclass(frozen=True)
class SetResult:
    code: int
    value: int
    before: PropertyDescriptor
    after: PropertyDescriptor
    sent: bool  # False when the camera already held the value


class RemoteSession:
    """One PC Remote session over an injected transport (PyUsbTransport or a test fake).

    Use as a context manager: `with RemoteSession(PyUsbTransport.open()) as camera:`.
    After any transport/protocol failure `usable` is False and every later call
    raises SessionUnusable without sending.
    """

    def __init__(self, transport, *, model=MODEL, clock=time.monotonic, sleep=time.sleep, io_timeout=10.0,
                 busy_attempts=5, busy_delay=0.1, ext_info_attempts=20, ext_info_delay=0.1,
                 readback_timeout=4.0, readback_interval=0.2):
        if busy_attempts < 1 or ext_info_attempts < 1 or readback_timeout <= 0 or readback_interval <= 0:
            raise ValueError('Retry counts and read-back timing must allow at least one attempt')
        self.transport, self.model = transport, model
        self._clock, self._sleep, self.io_timeout = clock, sleep, io_timeout
        self.busy_attempts, self.busy_delay = busy_attempts, busy_delay
        self.ext_info_attempts, self.ext_info_delay = ext_info_attempts, ext_info_delay
        self.readback_timeout, self.readback_interval = readback_timeout, readback_interval
        self.usable, self.connected, self.info = True, False, None
        self._operations = self._controls = None
        self._session_open, self._tid, self._started, self._closed = False, 1, False, False

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, *exc):
        self.close()

    # ------------------------------------------------------------ transactions
    def _take_tid(self, opcode):
        if opcode in (GET_DEVICE_INFO, OPEN_SESSION) and not self._session_open:
            return 0
        tid, self._tid = self._tid, (self._tid + 1) & 0xFFFFFFFF or 1
        return tid

    def _transact(self, opcode, params=(), data_out=None):
        """The choke point: gate, then exactly one PTP transaction."""
        check_operation(opcode, params, self._operations, self._controls)
        if not self.usable:
            raise SessionUnusable('An earlier failure left the camera session unusable; nothing was sent')
        tid = self._take_tid(opcode)
        command = pack_command(opcode, tid, params)
        try:
            self.transport.send(command, self.io_timeout)
            if data_out is not None:
                self.transport.send(pack_container(DATA, opcode, tid, data_out), self.io_timeout)
            reply, data = unpack_container(self.transport.receive(self.io_timeout)), None
            if reply.kind == DATA and data_out is None:
                if (reply.code, reply.tid) != (opcode, tid):
                    raise ProtocolError('Data phase for 0x%04X/%d arrived for 0x%04X/%d' %
                                        (reply.code, reply.tid, opcode, tid))
                data = reply.payload
                reply = unpack_container(self.transport.receive(self.io_timeout))
            if reply.kind != RESPONSE or reply.tid != tid:
                raise ProtocolError('Expected the response to 0x%04X/%d, got container type %d tid %d' %
                                    (opcode, tid, reply.kind, reply.tid))
        except BaseException:
            self.usable = False
            raise
        if reply.code != OK:
            error = response_error(reply.code, opcode)
            if isinstance(error, _FATAL_RESPONSES):
                self.usable = False
            raise error
        return Reply(reply.params, data)

    def _request(self, opcode, params=()):
        """A non-mutating transaction; Device Busy is retried with bounded back-off."""
        if opcode in MUTATING_OPERATIONS:
            raise OperationRefused('Operation 0x%04X changes the camera and is never retried here' % opcode)
        for attempt in range(1, self.busy_attempts + 1):
            try:
                return self._transact(opcode, params)
            except DeviceBusy:
                if attempt == self.busy_attempts:
                    raise
                self._sleep(self.busy_delay * 2 ** (attempt - 1))

    def _parse(self, parser, *args):
        try:
            return parser(*args)
        except DatasetError:
            self.usable = False
            raise

    # ------------------------------------------------------------ connection
    def connect(self):
        """GetDeviceInfo, OpenSession, SDIO_Connect 1 and 2, GetExtDeviceInfo, SDIO_Connect 3."""
        if self._started:
            raise PtpError('A RemoteSession connects once; create a new one')
        self._started = True
        try:
            device = self._parse(parse_device_info, self._request(GET_DEVICE_INFO).data or b'')
            if device.manufacturer != MANUFACTURER or device.model != self.model:
                raise ConnectError('Connected device is %s %s, not %s %s in PC Remote mode' % (
                    device.manufacturer, device.model, MANUFACTURER, self.model))
            missing = REQUIRED_OPERATIONS - device.operations
            if missing:
                raise ConnectError('Camera does not offer PC Remote operations %s; set USB Connection Mode '
                                   'to PC Remote' % ', '.join('0x%04X' % op for op in sorted(missing)))
            self._operations = device.operations
            self._open_session()
            self._sdio_connect(1)
            self._sdio_connect(2)
            ext = self._ext_device_info()
            self._controls = ext.controls
            self._sdio_connect(3)
        except BaseException:
            try:
                self.close()
            except Exception:
                pass  # report why the connection failed, not a secondary release error
            raise
        self.connected, self.info = True, ConnectInfo(device, ext)
        return self.info

    def _open_session(self):
        try:
            self._transact(OPEN_SESSION, (SESSION_ID,))
        except SessionAlreadyOpen:
            # A previous initiator left a session open: close it, retry once.
            self._session_open = True
            self._transact(CLOSE_SESSION)
            self._session_open = False
            try:
                self._transact(OPEN_SESSION, (SESSION_ID,))
            except SessionAlreadyOpen as exc:
                raise ConnectError('Camera still reports an open session after closing it') from exc
        self._session_open, self._tid = True, 1

    def _sdio_connect(self, phase):
        data = self._request(SDIO_CONNECT, (phase, 0, 0)).data
        if data is None or len(data) != 8:
            self.usable = False
            raise ProtocolError('SDIO_Connect phase %d returned %s instead of its 8-byte data phase' % (
                phase, 'no data phase' if data is None else '%d bytes' % len(data)))

    def _ext_device_info(self):
        for attempt in range(1, self.ext_info_attempts + 1):
            reply = self._request(SDIO_GET_EXT_DEVICE_INFO, (INITIATOR_VERSION,))
            if reply.data:
                break
            if attempt == self.ext_info_attempts:
                raise ConnectError('Camera returned empty extended device info %d times' % attempt)
            self._sleep(self.ext_info_delay)
        version = self._parse(lambda data: _Reader(data).u16(), reply.data)
        if version != INITIATOR_VERSION:
            raise ConnectError('Camera speaks Sony extension version 0x%04X; this tool requires 0x%04X' % (
                version, INITIATOR_VERSION))
        return self._parse(parse_ext_device_info, reply.data, reply.params[0] if reply.params else None)

    # ------------------------------------------------------------ properties
    def _require_connected(self):
        if not self.connected:
            raise SessionUnusable('The camera session is not connected; nothing was sent')

    def read_all(self):
        """Full 0x9209 snapshot (DiffOnly=0, no extended-range flag)."""
        self._require_connected()
        data = self._request(SDIO_GET_ALL_EXT_DEVICE_PROP_INFO, (0,)).data
        ext = self.info.ext
        properties, controls = self._parse(parse_all_properties, data or b'', ext.controls, ext.properties)
        return Snapshot(properties, controls, ext.properties)

    def read_property(self, code):
        """Fresh descriptor of one advertised property (0x9251 if offered, else 0x9209)."""
        self._require_connected()
        if code not in self.info.ext.properties:
            raise PropertyUnavailable('The camera did not advertise property 0x%04X' % code)
        if SDIO_GET_EXT_DEVICE_PROP not in self._operations:
            snapshot = self.read_all()
            if code not in snapshot.properties:
                raise PropertyUnavailable('The camera did not report property 0x%04X' % code)
            return snapshot.properties[code]
        row = self._parse(parse_property, self._request(SDIO_GET_EXT_DEVICE_PROP, (code,)).data or b'')
        if row.code != code:
            self.usable = False
            raise ProtocolError('Asked for property 0x%04X, camera described 0x%04X' % (code, row.code))
        return row

    def set_property(self, code, value):
        """Validate against a fresh descriptor, write once with 0x9205, then poll until it reads back.

        Raises ValidationError (nothing sent), ResponseError (camera refused),
        WriteIgnored/WriteCoerced (accepted but not applied), WriteUnverified
        (accepted, read-back failed) or a transport/protocol error. The last two
        leave the outcome unknown and the session unusable. Device Busy is the only
        reason to send again, and only after a fresh read.
        """
        self._require_connected()
        if code not in self.info.ext.properties:
            raise ValidationError(code, value, 'the camera did not advertise this property')
        for attempt in range(1, self.busy_attempts + 1):
            before = self.read_property(code)
            reason = before.refusal(value)
            if reason:
                raise ValidationError(code, value, reason)
            if before.current == value:
                return SetResult(code, value, before, before, False)
            try:
                self._transact(SDIO_SET_EXT_DEVICE_PROP_VALUE, (code,), _INTEGERS[before.datatype].pack(value))
            except DeviceBusy:
                if attempt == self.busy_attempts:
                    raise
                self._sleep(self.busy_delay * 2 ** (attempt - 1))
                continue
            try:
                after = self._await_value(code, value, before)
            except WriteNotApplied:
                raise
            except PtpError as exc:
                self.usable = False  # an unknown write outcome stops the session
                raise WriteUnverified(code, value, before.current) from exc
            return SetResult(code, value, before, after, True)

    def _await_value(self, code, value, before):
        deadline = self._clock() + self.readback_timeout
        while True:
            self._sleep(self.readback_interval)
            after = self.read_property(code)
            if after.current == value:
                return after
            if self._clock() >= deadline:
                error = WriteIgnored if after.current == before.current else WriteCoerced
                raise error(code, value, before.current, after.current)

    def close(self):
        """CloseSession when the session is open and healthy, then release the transport once.

        Never raises PtpError; a transport release error propagates.
        """
        if self._closed:
            return
        self._closed = True
        try:
            if self._session_open and self.usable:
                try:
                    self._transact(CLOSE_SESSION)
                except PtpError:
                    pass  # the camera ends the session itself when the interface is released
        finally:
            self._session_open = self.connected = False
            self.transport.close()


# ---------------------------------------------------------------- USB transport
VENDOR_ID = 0x054C
STILL_IMAGE_CLASS = (6, 1, 1)
MAX_CONTAINER = 16 * 1024 * 1024
READ_CHUNK = 64 * 1024  # a multiple of every bulk max-packet size


class Transport(Protocol):
    """Whole-container bulk I/O. Timeouts are seconds; failures raise TransportError/ProtocolError."""

    def send(self, container: bytes, timeout: float) -> None: ...

    def receive(self, timeout: float) -> bytes: ...

    def close(self) -> None: ...


def _still_image_interface(device):
    for configuration in device:
        for interface in configuration:
            kind = (interface.bInterfaceClass, interface.bInterfaceSubClass, interface.bInterfaceProtocol)
            if kind != STILL_IMAGE_CLASS:
                continue
            endpoints = list(interface)

            def pick(transfer, incoming):
                return [e for e in endpoints
                        if e.bmAttributes & 3 == transfer and bool(e.bEndpointAddress & 0x80) == incoming]
            bulk_out, bulk_in, interrupt_in = pick(2, False), pick(2, True), pick(3, True)
            if (len(bulk_out), len(bulk_in), len(interrupt_in)) != (1, 1, 1):
                raise ConnectError('Still-image interface has an unexpected endpoint layout')
            return interface, bulk_out[0], bulk_in[0]
    return None


def select_camera(devices):
    """The one Sony device (VID 0x054C, any PID) exposing a class 6/1/1 interface.

    Returns (device, interface, bulk_out, bulk_in).
    """
    matches = []
    for device in devices:
        if device.idVendor == VENDOR_ID:
            found = _still_image_interface(device)
            if found:
                matches.append((device, *found))
    if not matches:
        raise ConnectError('No Sony camera with a PC Remote (still-image) interface is connected. On the camera '
                           'set MENU > Setup > USB > USB Connection Mode to PC Remote; Mass Storage mode has none.')
    if len(matches) > 1:
        raise ConnectError('Connect only one Sony camera in PC Remote mode (found %d)' % len(matches))
    return matches[0]


def _milliseconds(seconds):
    return max(1, int(seconds * 1000))


def _usb_failure(exc, what):
    import usb.core
    if isinstance(exc, usb.core.USBTimeoutError):
        return TransportTimeout('USB %s timed out' % what)
    return TransportError('USB %s failed: %s' % (what, exc))


def _claim_pyusb(device, number):
    import usb.util
    usb.util.claim_interface(device, number)


def _release_pyusb(device, number):
    import usb.util
    try:
        usb.util.release_interface(device, number)
    finally:
        usb.util.dispose_resources(device)


def _enumerate_sony():
    import usb.core
    import usb.backend.libusb1
    import libusb_package
    backend = usb.backend.libusb1.get_backend(find_library=libusb_package.find_library)
    if backend is None:
        raise ConnectError('The libusb library was not found')
    return list(usb.core.find(find_all=True, idVendor=VENDOR_ID, backend=backend))


class PyUsbTransport:
    """Bulk-pipe PTP transport over pyusb/libusb. Event (interrupt) packets are not read."""

    def __init__(self, device, interface_number, bulk_out, bulk_in, *, clock=time.monotonic, release=None):
        self.device, self.interface_number = device, interface_number
        self._out, self._in, self._clock = bulk_out, bulk_in, clock
        self._release = release or _release_pyusb
        self._closed = False

    @classmethod
    def open(cls, *, devices=None, claim=None, release=None):
        """Enumerate (only here), select the camera and claim its interface; no PTP command is sent."""
        import usb.core
        device, interface, bulk_out, bulk_in = select_camera(_enumerate_sony() if devices is None else devices)
        number, release = interface.bInterfaceNumber, release or _release_pyusb
        try:
            (claim or _claim_pyusb)(device, number)
        except usb.core.USBError as exc:
            release(device, number)
            if exc.backend_error_code in (-3, -6):  # LIBUSB_ERROR_ACCESS, LIBUSB_ERROR_BUSY
                raise InterfaceBusy('The camera interface is held by another process (on macOS usually '
                                    'ptpcamerad; quit Photos, Image Capture, Lightroom and Imaging Edge)') from exc
            raise TransportError('Could not claim the camera interface: %s' % exc) from exc
        return cls(device, number, bulk_out, bulk_in, release=release)

    def send(self, container, timeout):
        try:
            written = self._out.write(container, _milliseconds(timeout))
            if written != len(container):
                raise TransportError('Short USB write: %d of %d bytes' % (written, len(container)))
            if len(container) % self._out.wMaxPacketSize == 0:
                self._out.write(b'', _milliseconds(timeout))  # zero-length packet ends the transfer
        except TransportError:
            raise
        except Exception as exc:
            raise _usb_failure(exc, 'write') from exc

    def _read(self, size, deadline):
        left = deadline - self._clock()
        if left <= 0:
            raise TransportTimeout('USB read timed out')
        packet = self._in.wMaxPacketSize
        try:
            return bytes(self._in.read(-(-size // packet) * packet, _milliseconds(left)))
        except Exception as exc:
            raise _usb_failure(exc, 'read') from exc

    def receive(self, timeout):
        deadline = self._clock() + timeout
        data = b''
        while not data:  # a zero-length packet may still be pending from the previous transfer
            data = self._read(READ_CHUNK, deadline)
        if len(data) < HEADER.size:
            raise ProtocolError('USB transfer of %d bytes is shorter than a PTP header' % len(data))
        length = HEADER.unpack_from(data)[0]
        if not HEADER.size <= length <= MAX_CONTAINER:
            raise ProtocolError('PTP container declares an implausible length %d' % length)
        buffer = bytearray(data)
        while len(buffer) < length:
            more = self._read(length - len(buffer), deadline)
            if not more:
                raise ProtocolError('PTP container ended %d bytes early' % (length - len(buffer)))
            buffer += more
        if len(buffer) != length:
            raise ProtocolError('Camera sent %d bytes for a %d-byte container' % (len(buffer), length))
        return bytes(buffer)

    def close(self):
        if not self._closed:
            self._closed = True
            self._release(self.device, self.interface_number)


# ---------------------------------------------------------------- macOS ptpcamerad
KNOWN_CAMERA_APPS = ('ptpcamerad', 'Photos', 'Image Capture', 'Adobe Lightroom Classic', 'Adobe Lightroom',
                     'Imaging Edge Desktop', 'Imaging Edge Webcam', 'Capture One')


def running_camera_apps(run=subprocess.run):
    """Names from KNOWN_CAMERA_APPS that are running now (pgrep -x; read-only)."""
    return [name for name in KNOWN_CAMERA_APPS
            if run(['/usr/bin/pgrep', '-x', name], capture_output=True, text=True, timeout=10).returncode == 0]


def claim_after_stopping_ptpcamerad(open_transport, *, consent, attempts=10, delay=0.2, run=subprocess.run,
                                    sleep=time.sleep, platform=sys.platform, uid=None):
    """macOS only, and only with consent=True: stop this user's ptpcamerad, then open.

    ptpcamerad (a per-user LaunchAgent) claims still-image interfaces and launchd
    may restart it, so each bounded attempt stops it again and immediately calls
    `open_transport` (e.g. PyUsbTransport.open). Never uses sudo and never touches
    other users' processes. Raises InterfaceBusy naming any camera app still running.
    """
    if consent is not True:
        raise ConsentRequired('Stopping ptpcamerad needs the user\'s explicit consent; nothing was done')
    if platform != 'darwin':
        raise PtpError('ptpcamerad exists only on macOS')
    uid = os.getuid() if uid is None else uid
    last = None
    for attempt in range(1, attempts + 1):
        result = run(['/usr/bin/pkill', '-9', '-U', str(uid), '-x', 'ptpcamerad'],
                     capture_output=True, text=True, timeout=10)
        if result.returncode not in (0, 1):  # 1 = no such process
            raise PtpError('pkill ptpcamerad failed with status %d: %s' % (result.returncode, result.stderr.strip()))
        try:
            return open_transport()
        except InterfaceBusy as exc:
            last = exc
        if attempt < attempts:
            sleep(delay)
    holders = running_camera_apps(run)
    raise InterfaceBusy('The camera interface is still held after %d attempts. %s' % (attempts, (
        'Running now: %s. Quit %s, then reconnect the camera.' % (', '.join(holders), 'them' if len(holders) > 1 else 'it')
        if holders else 'no known camera application is running; another process holds the camera'))) from last
