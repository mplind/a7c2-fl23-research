"""Lazy optional USB access for explicit LUT device commands only.

The firmware identity gate lives here. No primitive with a persistent effect on the camera (a setting
write or save, a CP unit write, or a native launch that can change anything) runs until
Camera.identify_programs has identified the programs just read from the camera as a supported build.
Staging worker, request and report files in /tmp/jiritsu stays ungated: those live in camera RAM
only. The exception is LAUNCHER (libJit.so): writing it is the launch, because the camera runs it at
once. temp_write refuses it; only invoke writes it, through Camera._launch, after the gate.
"""
import importlib,struct,sys,time
from pathlib import Path
from . import buildprofile, firmware
from .buildprofile import UnsupportedFirmware
from .nativebuild import ROOT

# Writing this /tmp/jiritsu file starts a native worker. Other modules name it through this constant.
LAUNCHER='libJit.so'
NOT_STAGING='Writing libJit.so launches a native worker; only devicesession.invoke may launch'
TEMP_NAMES={LAUNCHER,'lut-program-staged.so','lut-names-staged.so','lut-runtime-staged.so',
    'portrait.staged.so','portrait.request','portrait.result',
    'a7c2.install.request','a7c2.install.result','a7c2.names.request','a7c2.names.result',
    'a7c2.wbi.request','a7c2.wbi.result','a7c2.runtime.result','a7c2.probe.result'}
# The only native launches that run before identification. ('runtime', 0) is the pinned runtime.so
# model/boot/span probe; ('probe', 0) is a read-only probe (the sound registry and vertical-display
# probes). Neither stages a request file. Every other (kind, mode) can change the camera.
READ_ONLY_NATIVE=frozenset({('runtime',0),('probe',0)})
UNIDENTIFIED='尚未识别此相机的固件版本，未写入任何内容。'


def read_only_launch(kind,mode,request):
    """The one place that decides whether a native launch may run before identification."""
    return (kind,mode) in READ_ONLY_NATIVE and request is None

def modules():
    folder=ROOT/('src/camera_runtime' if (ROOT/'src/camera_runtime').is_dir() else 'src/fl23');sys.path[:0]=[str(folder),str(folder/'vendor')]
    transport=importlib.import_module('transport');core=importlib.import_module('core')
    if Path(transport.__file__).resolve()!=folder/'transport.py' or Path(core.__file__).resolve()!=folder/'core.py':
        raise ValueError('Unexpected camera transport module already loaded')
    return transport,core

class Camera:
    def __init__(self,expected=None,*,allow_service_resume=False):
        self.expected=expected;self.healthy=True;self.identity_pending=False;self.programs_pinned=False
        self.allow_service_resume=allow_service_resume
        self.firmware_build=None
    def __enter__(self):
        from .devicelock import DeviceLock
        self.lock=DeviceLock();self.lock.__enter__()
        try:return self._connect()
        except BaseException:
            self.lock.__exit__(*sys.exc_info());raise
    def _connect(self):
        transport,self.core=modules()
        normal={k:self.expected[k] for k in ['model','serial_sha256']} if self.expected and self.expected.get('serial_sha256') else None
        self.service_only=False
        import usb.core,usb.backend.libusb1
        backend=usb.backend.libusb1.get_backend(find_library=transport.libusb_package.find_library)
        detected=usb.core.find(idVendor=0x054c,idProduct=0x0e8a,backend=backend)
        service_present=False
        if detected is None and self.allow_service_resume:
            service=usb.core.find(idVendor=0x054c,idProduct=0x0336,backend=backend)
            service_present=service is not None
            if service_present:transport.usb.util.dispose_resources(service)
        if detected is None and not service_present:
            # A successful auth.stop re-enumerates asynchronously. Wait for
            # the normal descriptor locally; never re-authenticate service.
            wait=15
            if sys.platform=='darwin':
                # The camera may be showing its USB mode menu; MDHan waits 60 s.
                from macos_host import MSC_PROMPT,NORMAL_RETURN_SECONDS
                print('等待相机普通 USB 连接（最多 %d 秒）。'%NORMAL_RETURN_SECONDS+MSC_PROMPT,flush=True)
                wait=NORMAL_RETURN_SECONDS
            deadline=time.monotonic()+wait
            while detected is None and time.monotonic()<deadline:
                time.sleep(.5)
                detected=usb.core.find(idVendor=0x054c,idProduct=0x0e8a,backend=backend)
        if detected is not None:
            transport.usb.util.dispose_resources(detected)
            released=sys.platform=='darwin'
            if released:
                # MDHan's order: release camera storage before the first libusb open.
                from macos_host import unmount_camera
                unmount_camera()
            from . import usbidentity
            usb_serial=usbidentity.capture(transport)
            usbidentity.require_match(self.expected,usb_serial)
            try:
                self.link=transport.Session(normal,media_released=released);self.link.__enter__()
            except (transport.ReadinessFailure,transport.SonyBusyFailure) as exc:
                from .usbservice import allowed_initial_busy,open_service
                if not allowed_initial_busy(transport,exc):raise
                print('Known initial storage busy/no-media state. Acquiring service access for pinned-program/native-model identification; no firmware writes.',flush=True)
                self.link=open_service(transport);self.identity_pending=True
        else:
            if self.allow_service_resume and self.expected and self.expected.get('model')==self.core.MODEL:
                print('普通 USB 身份未出现；只读取已有服务会话的机身序列，核对后续接，不重复认证。',flush=True)
                self.link=transport.RecoverySession(self.expected);self.link.__enter__()
                self.identity=dict(self.link.identity,identification_method='recorded-body-existing-service')
                self.service_only=False
                return self
            raise ValueError('相机没有以普通“海量存储”身份连接（可能仍停在上次的服务模式 054C:0336）。'
                             '请拔掉 USB、关机并取出电池约 1 分钟，再开机选择海量存储、接回 USB 后重试；本次没有写入相机。'
                             '（Normal Mass Storage USB serial is required for body binding）')
        try:
            self.identity=dict(self.link.identity,usb_serial_sha256=usb_serial)
            if self.identity_pending and self.expected and self.expected.get('model')==self.core.MODEL:
                self.identity.update(model=self.core.MODEL,identification_method='stable-usb-serial-matches-native-verified-job')
                self.identity_pending=False
        except BaseException:
            self.link.__exit__(*sys.exc_info());raise
        return self
    def identify_programs(self,ap,cp):
        """Identify the build of appFw.so and cpapp-b.bin just read from this camera. Writes stay
        refused until this succeeds; a refusal also withdraws any earlier identification."""
        self.firmware_build=None
        self.firmware_build=buildprofile.identify(ap,cp)
        return self.firmware_build
    def require_build(self):
        """The identified build. Every write primitive calls this first."""
        if self.firmware_build is None:raise UnsupportedFirmware(UNIDENTIFIED)
        return self.firmware_build
    def pin_programs(self,ap,cp):
        self.identify_programs(ap,cp)
        from .device_layout import identify,structural
        self.program_identity=(structural if getattr(self,'byte_checks',False) else identify)(ap,cp);self.programs_pinned=True
        return self.program_identity
    def confirm_identity(self,runtime):
        if not self.programs_pinned or runtime.get('model_index')!=16:raise ValueError('Pinned programs and actual native model proof are required')
        self.identity.update(model=self.core.MODEL,identification_method='pinned-programs-and-native-model')
        self.identity_pending=False
    def __exit__(self,*args):
        try:
            self.healthy=self.link.healthy;return self.link.__exit__(*args)
        finally:self.lock.__exit__(*args)
    def read(self,path,missing=False):
        try:return self.link.read('/tmp/jiritsu/../../'+path.lstrip('/'),missing)
        except BaseException:
            # Name the file; a channel error is otherwise reported generically.
            print('读取相机文件时 USB 通信出错：'+path,flush=True)
            raise
    def temp_read(self,name,missing=False):
        if name not in TEMP_NAMES:raise ValueError('Unowned temporary name')
        return self.link.read('/tmp/jiritsu/'+name,missing)
    def temp_write(self,name,data):
        """Stage a file in camera RAM. Never libJit.so: writing that launches a worker (see _launch)."""
        if name==LAUNCHER:raise ValueError(NOT_STAGING)
        if self.service_only:raise ValueError('Service-only recovery is read-only; reconnect normal USB identity before new execution')
        if not self.programs_pinned:raise ValueError('Verify complete source programs before native execution')
        if self.identity_pending and (name!='lut-runtime-staged.so' or not self._pinned_runtime(data)):
            raise ValueError('Only the pinned read-only model/runtime probe is allowed before model confirmation')
        if name not in TEMP_NAMES or not data or len(data)>65536:raise ValueError('Invalid job temporary data')
        self._jiritsu_write(name,data)
    def temp_remove(self,name):
        if name not in TEMP_NAMES:raise ValueError('Unowned temporary name')
        self._jiritsu_remove(name)
    def _pinned_runtime(self,data):
        return firmware.sha(data)==self.core.assets()['files']['runtime.so']
    def _launch(self,blob):
        """Write libJit.so, which the camera runs at once. Only devicesession.invoke calls this, after
        its firmware gate; before model confirmation only the pinned read-only runtime.so may run."""
        if self.service_only:raise ValueError('Service-only recovery is read-only; reconnect normal USB identity before new execution')
        if not self.programs_pinned:raise ValueError('Verify complete source programs before native execution')
        if self.identity_pending and not self._pinned_runtime(blob):
            raise ValueError('Only the pinned read-only model/runtime probe is allowed before model confirmation')
        if not blob or len(blob)>65536:raise ValueError('Invalid native worker')
        self.link.select('/tmp/jiritsu/'+LAUNCHER);return self.link.jiritsu(16,b'\0\xff\0'+blob)
    # The raw /tmp/jiritsu file commands. Each session class checks its own namespace first.
    def _jiritsu_write(self,name,data):
        if name==LAUNCHER:raise ValueError(NOT_STAGING)
        self.link.select('/tmp/jiritsu/'+name);return self.link.jiritsu(16,b'\0\xff\0'+data)
    def _jiritsu_remove(self,name):
        self.link.select('/tmp/jiritsu/'+name);return self.link.jiritsu(18,b'\0\xff')
    def snapshot(self,memory):return self.link.call(self.link.camera.getBackupPresetData,memory)
    def records(self,raw):return self.core.backup_records(raw)
    def property_read(self,key):return self.link.call(self.link.camera.readBackup,key)
    def property_write(self,key,value,allowlist):
        self.require_build()
        if self.service_only:raise ValueError('Service-only recovery cannot write settings')
        if self.identity_pending or not self.programs_pinned:raise ValueError('Verified model and complete programs required for settings writes')
        if key not in allowlist or key>>16!=0x02cf or not value or len(value)>4:raise ValueError('Setting outside selected AP descriptor plan')
        return self.link.call(self.link.camera.writeBackup,key,value)
    def cp_write(self,key,value):
        self.require_build()
        if self.service_only:raise ValueError('Service-only recovery cannot write settings')
        if self.identity_pending or not self.programs_pinned:raise ValueError('Verified model and complete programs required for settings writes')
        return self.link.cp_write(key,value)
    def save_settings(self,group=0x02cf):
        """Save the AP look group (0x02cf) or the CP colour group (0x02a4) to flash."""
        self.require_build()
        if self.service_only:raise ValueError('Service-only recovery cannot save settings')
        if self.identity_pending or not self.programs_pinned:raise ValueError('Verified model and complete programs required before saving settings')
        if group not in (0x02cf,0x02a4):raise ValueError('Settings group outside the project scope')
        return self.link.call(self.link.camera.saveBackup,group)
    def mark_unknown(self):self.link.healthy=False;self.healthy=False

def clear_stale_probe(camera,record):
    """Remove a lone report of the read-only probe, which never changes the camera.

    Only when it is the sole project temporary file: no worker, request, other
    result or preload. Its bytes are recorded before removal. Anything else
    still stops as an unaccounted operation.
    """
    from .checkpointjob import TEMPS
    probe='a7c2.probe.result'
    raw=camera.temp_read(probe,True)
    if raw is None:return
    # Every project worker namespace (direct, checkpoint, FL23/sound runtime).
    others=(TEMP_NAMES|TEMPS|{'a7c2-preview-staged.so','shutter.staged.so','shutter.probe.result',
                              'shutter.custom.lease'})-{probe}
    if any(camera.link.read('/tmp/jiritsu/'+n,True) is not None for n in sorted(others)):return
    if camera.read('/etc/ld.so.preload',True):return
    record('stale_probe_result_removed',bytes=len(raw),sha256=firmware.sha(raw),contents_hex=raw[:4096].hex())
    if camera.temp_read(probe,True)!=raw:raise ValueError('Temporary state changed during cleanup: '+probe)
    camera.temp_remove(probe)
    if camera.temp_read(probe,True) is not None:raise ValueError('Temporary cleanup incomplete: '+probe)
    print('已清理上次只读检测留下的报告（不影响相机内容），继续本次操作。',flush=True)

def invoke(camera,blob,*,kind,stage,request,result,contents,mode,decode,record,save_raw,extras=()):
    """One invocation, never retries or cleans an unknown operation.

    `kind` names what the worker is; with `mode` it decides whether the launch only reads. Any other
    launch needs an identified build, checked before anything is staged."""
    if not read_only_launch(kind,mode,request):camera.require_build()
    names=[n for n in [stage,request,LAUNCHER,result,*extras] if n is not None]
    clear_stale_probe(camera,record)
    for name in names:
        if camera.temp_read(name,True) is not None:raise ValueError('Existing temporary state needs recovery: '+name)
    if camera.read('/etc/ld.so.preload',True):raise ValueError('Existing preload configuration requires inspection')
    expected={stage:blob,LAUNCHER:blob}
    record('native_stage_intent',stage=stage,result=result,mode=mode,worker_sha256=firmware.sha(blob),request=request,contents_hex=contents.hex() if contents else None)
    camera.temp_write(stage,blob)
    if camera.temp_read(stage)!=blob:raise ValueError('Worker staging readback differs')
    if request is not None:
        expected[request]=contents;camera.temp_write(request,contents)
        if camera.temp_read(request)!=contents:raise ValueError('Request staging readback differs')
    record('native_intent',stage=stage,result=result,mode=mode,worker_sha256=firmware.sha(blob))
    try:
        camera._launch(blob)
        raw=camera.temp_read(result);save_raw(raw)
        parsed=decode(raw)
    except BaseException:
        camera.mark_unknown();raise
    expected[result]=raw
    for extra in extras:
        value=camera.temp_read(extra)
        extra_info=None
        if extra=='a7c2.probe.result':
            extra_info=camera.core.parse_native('probe',value)
            if isinstance(parsed,dict) and isinstance(extra_info,dict):
                parsed['usr_mount_readonly']=extra_info.get('usr_mount_readonly')
        expected[extra]=value
        record('native_extra_result',name=extra,sha256=firmware.sha(value),details=extra_info)
    record('native_result_verified',stage=stage,mode=mode,result=parsed)
    for name in reversed(names):
        actual=camera.temp_read(name,True)
        if actual is not None:
            if actual!=expected[name]:raise ValueError('Preserve unexpected temporary contents: '+name)
            camera.temp_remove(name)
        if camera.temp_read(name,True) is not None:raise ValueError('Temporary cleanup incomplete: '+name)
    record('native_cleanup_verified',stage=stage,mode=mode)
    return parsed
