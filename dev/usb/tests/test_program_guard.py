"""The root conftest's guard holds in this test tree too, not only under dev/desktop: no test may run
ioreg or diskutil, which read and unmount the Mac's USB devices and disks (an attached camera's among
them), nor reach the administrator prompt."""
from pathlib import Path
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[3]


@pytest.mark.parametrize('argv, name', [
    (['/usr/sbin/diskutil', 'unmountDisk', '/dev/disk9'], 'diskutil'),
    (['/usr/sbin/ioreg', '-p', 'IOService', '-r', '-c', 'IOUSBHostDevice', '-l', '-a'], 'ioreg'),
    (['sudo', '-n', 'true'], 'sudo'),
    ('diskutil info -plist /dev/disk9', 'diskutil'),
])
def test_the_mac_disk_and_usb_commands_are_refused_here(blocked_programs, argv, name):
    with pytest.raises(AssertionError, match='Forbidden in tests'):
        subprocess.run(argv, capture_output=True)
    assert blocked_programs == [name]
    blocked_programs.clear()  # this test made the attempt on purpose


def test_the_real_camera_unmount_cannot_reach_the_mac(blocked_programs):
    sys.path.insert(0, str(ROOT / 'src/camera_runtime'))
    import macos_host
    with pytest.raises(AssertionError, match='Forbidden in tests'):
        macos_host.unmount_camera()
    assert blocked_programs and set(blocked_programs) <= {'ioreg', 'diskutil'}
    blocked_programs.clear()


def test_ordinary_commands_still_run(blocked_programs):
    done = subprocess.run([sys.executable, '-c', 'print(1)'], capture_output=True, text=True)
    assert done.stdout.strip() == '1' and blocked_programs == []
