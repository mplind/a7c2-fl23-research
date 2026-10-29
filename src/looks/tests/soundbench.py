"""Test-only: boot_trial's shutter-sound Save and Restore with every native step simulated, on a camera
whose two program files are short stand-ins playing a named build (simbuild.CarriesBuild). One bench
for the sound tests of every tree: dev/shutter_sound/tests/test_boot_trial.py and
dev/desktop/test_port_saved_bytes.py.

The simulated Save writes the custom sound's two files (boot_trial.PATHS) and the 8-byte program change
'original' -> 'modified' at the start of appFw.so; Restore writes 'original' back and removes the files.
`fault` makes one step go wrong: 'file_readback' (the CSV reads back other bytes), 'lost_ap_ack' (the
program write's result is lost) or 'restore_readback' (appFw.so reads back wrong during a restore).
"""
from contextlib import ExitStack
import json
from pathlib import Path
from unittest.mock import patch

import boot_trial
import trial
from simbuild import PUBLIC, CarriesBuild

IDENTITY = {'model': 'ILCE-7CM2', 'serial_sha256': 'synthetic'}
STOCK = {'/usr/lib/appFw.so': b'original-unrelated', '/cp/cpapp-b.bin': b'unchanged CP'}
PAYLOAD = bytes(64)


class SoundCamera(CarriesBuild):
    core = None

    def __init__(self, bench, build):
        self.bench, self.carries = bench, build

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def read(self, path, missing=False):
        bench = self.bench
        if bench.fault == 'file_readback' and path == boot_trial.PATHS[1]:
            return b'corrupt'
        if bench.fault == 'restore_readback' and bench.restoring and path == '/usr/lib/appFw.so':
            return b'wrong'
        return bench.files.get(path) if missing else bench.files[path]

    def snapshot(self, memory):
        return b'unchanged settings'

    def records(self, raw):
        return raw


class SoundBench(ExitStack):
    """`with SoundBench() as bench:` patches boot_trial's native steps for the block. bench.files are
    the camera's files, bench.events every connection and native step in order, bench.planned_builds
    the build each Save planned for; bench.connect(build) is a camera factory for a camera playing
    `build`, and bench.install(folder, build) runs a complete Save there and returns its job folder."""

    def __init__(self):
        super().__init__()
        self.files, self.events, self.planned_builds = dict(STOCK), [], []
        self.fault, self.restoring = None, False

    def __enter__(self):
        super().__enter__()
        for target, value in ((boot_trial, dict(prepare=self.prepare, invoke_files=self.invoke_files,
                                                probe=self.probe, program_worker=self.reverse_worker,
                                                require_dependencies=lambda: None)),
                              (trial, dict(run_native=self.run_native))):
            for name, replacement in value.items():
                self.enter_context(patch.object(target, name, replacement))
        self.enter_context(patch('looktool.devicesettings.compare'))
        return self

    def connect(self, build=PUBLIC):
        def factory(expected):
            assert expected == IDENTITY, expected
            self.events.append('connect')
            return SoundCamera(self, build)
        return factory

    def install(self, folder, build=PUBLIC):
        """A completed shutter-sound Save on a camera playing `build`; the job folder."""
        native, audio, job = self.inputs(folder)
        boot_trial.install(job, Path(folder) / 'backup2', native, audio, PAYLOAD, 100, camera_factory=self.connect(build))
        return job

    @staticmethod
    def inputs(folder):
        """(native job, audio job, job folder to create) for a Save in `folder`."""
        folder = Path(folder)
        native, audio, job = folder / 'native', folder / 'audio', folder / 'job'
        folder.mkdir(parents=True, exist_ok=True)
        for path, value in ((native, {'identity': IDENTITY}),
                            (audio, {'identity': IDENTITY, 'wire_format': 0, 'owner_audio_correct': True})):
            path.mkdir()
            (path / 'job.private.json').write_text(json.dumps(value))
        (audio / 'payload.private.bin').write_bytes(PAYLOAD)
        return native, audio, job

    def prepare(self, ap, cp, value, output, zig, *, build):
        self.planned_builds.append(build)
        root = Path(output)
        root.mkdir()
        (root / 'audio').write_bytes(value)
        (root / 'csv').write_bytes(b'private CSV')
        return {'appFw.so': b'modified' + ap[8:], 'cpapp-b.bin': cp}, {
            'windows': [{'offset': 0, 'before_hex': b'original'.hex(), 'after_hex': b'modified'.hex()}],
            'program': {'path': 'forward', 'windows': 1, 'sizes': [len(ap), len(cp)]},
            'files': 'fileworker', 'probe': 'probe', 'wbi': 'wbi',
            'audio': str(root / 'audio'), 'csv': str(root / 'csv')}

    def invoke_files(self, camera, root, state, worker_path, mode):
        self.events.append(('files', mode))
        if mode == 1:
            for path, name in zip(boot_trial.PATHS, ('audio', 'csv')):
                self.files[path] = Path(state['components'][name]).read_bytes()
        elif mode == 2:
            for path in boot_trial.PATHS:
                del self.files[path]
        return {'native_success': True}

    def run_native(self, camera, root, state, blob, kind, mode=0, plan=None):
        self.events.append((kind, mode, str(blob)))
        if kind == 'program' and mode == 1:
            self.restoring = str(blob) == 'reverse'
            prefix = b'original' if self.restoring else b'modified'
            self.files['/usr/lib/appFw.so'] = prefix + self.files['/usr/lib/appFw.so'][8:]
            if self.fault == 'lost_ap_ack':
                raise TimeoutError('lost AP commit result')
        return {}

    def probe(self, camera, root, state, components):
        self.events.append('probe')
        return {'image_mode': '0'}

    @staticmethod
    def reverse_worker(ap, cp, edits, output, zig):
        return {'path': 'reverse', 'windows': 1, 'sizes': [len(ap), len(cp)]}
