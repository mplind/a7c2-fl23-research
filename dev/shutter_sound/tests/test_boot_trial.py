import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / 'src/looks/tests'))
import boot_trial
from simbuild import PUBLIC
from soundbench import PAYLOAD, SoundBench
from looktool.buildprofile import BUILDS


class BootTrialOrderingTests(unittest.TestCase):
    def scenario(self, check, carries=PUBLIC):
        """Run `check(job, state, install, factory, audio)` on soundbench's simulated Save and Restore:
        `state` is the bench (its files, events, fault and planned_builds), `factory` a camera playing
        `carries`."""
        with tempfile.TemporaryDirectory() as directory, SoundBench() as bench:
            native, audio, job = bench.inputs(directory)
            factory = bench.connect(carries)

            def install():
                return boot_trial.install(job, Path(directory) / 'backup2', native, audio, PAYLOAD, 100,
                                          camera_factory=factory)
            check(job, bench, install, factory, audio)

    def test_install_plans_against_the_cameras_identified_build(self):
        for build in BUILDS:
            def check(job, state, install, factory, audio):
                install()
                self.assertEqual(state.planned_builds, [build])
            with self.subTest(build=build.key):
                self.scenario(check, carries=build)

    def test_bad_file_readback_stops_before_any_AP_commit(self):
        def check(job, state, install, factory, audio):
            state.fault = 'file_readback'
            with self.assertRaisesRegex(ValueError, 'AP hook was not invoked'): install()
            self.assertFalse(any(isinstance(e, tuple) and e[:2] == ('program', 1) for e in state.events))
            self.assertEqual(state.files['/usr/lib/appFw.so'], b'original-unrelated')
        self.scenario(check)

    def test_lost_AP_ack_keeps_resources_and_does_not_replay(self):
        def check(job, state, install, factory, audio):
            state.fault = 'lost_ap_ack'
            with self.assertRaises(TimeoutError): install()
            self.assertEqual(json.loads((job / 'job.private.json').read_text())['phase'], 'needs_review')
            self.assertTrue(all(path in state.files for path in boot_trial.PATHS))
            events = list(state.events)
            with self.assertRaises(FileExistsError): install()
            self.assertEqual(state.events, events)
            self.assertNotIn(('files', 2), events)
        self.scenario(check)

    def test_restore_readback_failure_keeps_audio_files(self):
        def check(job, state, install, factory, audio):
            install()
            state.fault = 'restore_readback'
            with self.assertRaisesRegex(ValueError, 'audio files must remain'): boot_trial.restore(job, camera_factory=factory)
            self.assertTrue(all(path in state.files for path in boot_trial.PATHS))
            self.assertNotIn(('files', 2), state.events)
        self.scenario(check)

    def test_full_ordering_and_restore_preserve_later_unrelated_edits(self):
        def check(job, state, install, factory, audio):
            install()
            state.files['/usr/lib/appFw.so'] = state.files['/usr/lib/appFw.so'][:-1] + b'Z'
            boot_trial.restore(job, camera_factory=factory)
            self.assertEqual(state.files['/usr/lib/appFw.so'], b'original-unrelateZ')
            self.assertEqual(state.files['/cp/cpapp-b.bin'], b'unchanged CP')
            self.assertLess(state.events.index(('files', 1)), state.events.index(('program', 1, 'forward')))
            self.assertLess(state.events.index(('program', 1, 'reverse')), state.events.index(('files', 2)))
        self.scenario(check)

    def test_invalid_encoded_audio_never_opens_a_camera(self):
        def check(job, state, install, factory, audio):
            (audio/'payload.private.bin').write_bytes(b'bad')
            with self.assertRaisesRegex(ValueError,'another body or payload'): install()
            self.assertFalse(state.events)
            self.assertFalse(job.exists())
        self.scenario(check)


if __name__ == '__main__':
    unittest.main()
