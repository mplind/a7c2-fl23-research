"""The suite-wide guard: no test may start a worker, ask for administrator rights, enumerate USB or
stop macOS camera services, and an attempt fails the test even when Qt swallows it."""
import os
import subprocess
import sys

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import pytest
from PySide6 import QtCore, QtWidgets as W


def test_an_attempt_inside_a_qt_slot_is_recorded(blocked_side_effects):
    W.QApplication.instance() or W.QApplication([])
    button = W.QPushButton()
    button.clicked.connect(lambda: QtCore.QProcess().start('/bin/echo', ['never']))
    button.click()  # Qt prints and swallows the exception raised inside the slot
    assert blocked_side_effects == ['starting a worker process']
    blocked_side_effects.clear()  # this test made the attempt on purpose


@pytest.mark.parametrize('argv,name', [
    (['/usr/bin/open', '-a', 'Terminal', '/tmp/x.command'], 'open -a Terminal'),
    (['sudo', '-n', 'true'], 'sudo'),
    (['/usr/bin/pkill', '-9', '-x', 'ptpcamerad'], 'pkill'),
    (['/usr/bin/pgrep', '-x', 'Photos'], 'pgrep'),
])
def test_commands_that_reach_the_admin_prompt_or_camera_services_are_refused(blocked_side_effects, argv, name):
    with pytest.raises(AssertionError):
        subprocess.run(argv)
    assert blocked_side_effects == [name]
    blocked_side_effects.clear()


def test_ordinary_commands_still_run(blocked_side_effects):
    done = subprocess.run([sys.executable, '-c', 'print(1)'], capture_output=True, text=True)
    assert done.stdout.strip() == '1' and blocked_side_effects == []


def test_ptpremote_process_defaults_are_refused(blocked_side_effects):
    from camera_runtime import ptpremote
    with pytest.raises(AssertionError):
        ptpremote.running_camera_apps()
    with pytest.raises(AssertionError):
        ptpremote.claim_after_stopping_ptpcamerad(lambda: 'transport', consent=True, platform='darwin')
    assert blocked_side_effects == ['pgrep', 'pkill']
    blocked_side_effects.clear()


def test_usb_enumeration_is_refused(blocked_side_effects):
    import usb.core
    with pytest.raises(AssertionError):
        usb.core.find(find_all=True)
    assert blocked_side_effects == ['USB enumeration']
    blocked_side_effects.clear()
