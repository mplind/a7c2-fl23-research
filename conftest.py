"""Automated tests must never access a physical camera, nor the Mac's USB devices, disks or
administrator prompt. These guards apply to every test tree."""
import pytest
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parent/'src/shutter_sound'))

# Commands that reach the administrator prompt, stop macOS camera services, or read or unmount the
# Mac's USB devices and disks (macos_host's ioreg and diskutil, which act on an attached camera).
DANGEROUS_PROGRAMS = ('sudo', 'pkill', 'kill', 'killall', 'pgrep', 'osascript', 'ioreg', 'diskutil')


def dangerous(argv):
    """The name of a command that would reach the administrator prompt, camera services or the Mac's
    USB devices and disks, or None."""
    words = argv.split() if isinstance(argv, (str, bytes)) else [str(word) for word in argv]
    program = Path(str(words[0])).name if words else ''
    if program in DANGEROUS_PROGRAMS:
        return program
    if program == 'open' and 'Terminal' in words:
        return 'open -a Terminal'
    return None


@pytest.fixture(autouse=True)
def no_physical_usb(monkeypatch):
    import usb.core
    def forbidden(*args,**kwargs):
        raise AssertionError('Physical USB enumeration is forbidden in offline tests; supply a fake camera')
    monkeypatch.setattr(usb.core,'find',forbidden)


@pytest.fixture(autouse=True)
def blocked_programs(monkeypatch):
    """Refuse every dangerous() command run through subprocess.run, in every test tree. Each attempt is
    recorded in the list this yields and fails the test at teardown, even when the code under test
    catches the refusal."""
    import subprocess
    attempts, real_run = [], subprocess.run

    def guarded_run(argv, *args, **kwargs):
        name = dangerous(argv)
        if name:
            attempts.append(name)
            raise AssertionError('Forbidden in tests: ' + name)
        return real_run(argv, *args, **kwargs)
    monkeypatch.setattr(subprocess, 'run', guarded_run)
    yield attempts
    assert not attempts, 'This test tried: ' + ', '.join(attempts)
