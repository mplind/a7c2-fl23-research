"""Test-only: simulated and offline cameras that carry a named, supported firmware build.

Production cameras refuse every write until Camera.identify_programs has identified the programs
read from them. Simulations use small stand-in programs, so they say which build they play here.
"""
from unittest.mock import patch

from looktool import buildprofile, devicesession

PUBLIC = buildprofile.BUILDS[0]


class CarriesBuild:
    """Mixin for a simulated camera. Its stand-in programs play the build in `carries` (Sony's
    public 2.01); a test that sets `carries = None` gets the real identification, which refuses
    them. Writes check the production require_build."""
    carries = PUBLIC
    firmware_build = None
    require_build = devicesession.Camera.require_build

    def identify_programs(self, ap, cp):
        self.firmware_build = None
        self.firmware_build = self.carries or buildprofile.identify(ap, cp)
        return self.firmware_build


def identified(camera, build=PUBLIC):
    """Identify a production session's stand-in programs as `build`, through identify_programs."""
    with patch.object(buildprofile, 'identify', return_value=build):
        camera.identify_programs(b'stand-in appFw.so', b'stand-in cpapp-b.bin')
    return camera


def saved_as(build, programs):
    """Patch buildprofile.identify so that stand-in programs `programs` ({'appFw.so': …,
    'cpapp-b.bin': …}: a backup or job saved before builds were recorded, or a prepared Sony
    reference) identify as `build`. Any other pair is refused, as the real identification refuses
    stand-ins."""
    def identify(ap, cp):
        if (ap, cp) != (programs['appFw.so'], programs['cpapp-b.bin']):
            raise buildprofile.UnsupportedFirmware(buildprofile.UNSUPPORTED % ('0' * 16, '0' * 16))
        return build
    return patch.object(buildprofile, 'identify', side_effect=identify)
