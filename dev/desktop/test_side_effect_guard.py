"""The suite-wide guard: no test may start a worker, ask for administrator rights, enumerate USB, stop
macOS camera services or open a dialog it has not answered itself, and an attempt fails the test even when
Qt swallows it."""
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
    (['/usr/sbin/diskutil', 'unmountDisk', '/dev/disk9'], 'diskutil'),
    (['/usr/sbin/ioreg', '-p', 'IOService', '-a'], 'ioreg'),
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


# Every static dialog function Qt offers, with arguments it accepts. Each runs a modal dialog of its own,
# which no exec patch reaches. Kept by hand: the guard's own list is what is under test.
STATIC_DIALOGS = [
    (W.QMessageBox, 'information', (None, 'Title', 'Text')), (W.QMessageBox, 'warning', (None, 'Title', 'Text')),
    (W.QMessageBox, 'critical', (None, 'Title', 'Text')), (W.QMessageBox, 'question', (None, 'Title', 'Text')),
    (W.QMessageBox, 'about', (None, 'Title', 'Text')), (W.QMessageBox, 'aboutQt', (None,)),
    (W.QFileDialog, 'getOpenFileName', (None, 'Title')), (W.QFileDialog, 'getOpenFileNames', (None, 'Title')),
    (W.QFileDialog, 'getSaveFileName', (None, 'Title')), (W.QFileDialog, 'getExistingDirectory', (None, 'Title')),
    (W.QFileDialog, 'getOpenFileUrl', (None, 'Title')), (W.QFileDialog, 'getOpenFileUrls', (None, 'Title')),
    (W.QFileDialog, 'getSaveFileUrl', (None, 'Title')), (W.QFileDialog, 'getExistingDirectoryUrl', (None, 'Title')),
    (W.QInputDialog, 'getText', (None, 'Title', 'Label')), (W.QInputDialog, 'getMultiLineText', (None, 'Title', 'Label')),
    (W.QInputDialog, 'getItem', (None, 'Title', 'Label', ['one'])), (W.QInputDialog, 'getInt', (None, 'Title', 'Label')),
    (W.QInputDialog, 'getDouble', (None, 'Title', 'Label')), (W.QColorDialog, 'getColor', ()), (W.QFontDialog, 'getFont', ()),
]


@pytest.fixture
def dialogs_closed():
    """Rejects every modal dialog that opens, so a dialog the guard misses fails its test instead of
    waiting offscreen for a click forever."""
    app = W.QApplication.instance() or W.QApplication([])
    closed = []

    def close():
        dialog = app.activeModalWidget()
        if dialog is not None:
            closed.append(type(dialog).__name__)
            dialog.reject()
    timer = QtCore.QTimer()
    timer.timeout.connect(close)
    timer.start(50)
    yield closed
    timer.stop()


@pytest.mark.parametrize('owner, name, arguments', STATIC_DIALOGS,
                         ids=[owner.__name__ + '.' + name for owner, name, _ in STATIC_DIALOGS])
def test_a_static_dialog_is_refused_instead_of_waiting_for_a_click(blocked_side_effects, dialogs_closed,
                                                                   owner, name, arguments):
    with pytest.raises(AssertionError, match='Forbidden in tests: opening a modal dialog'):
        getattr(owner, name)(*arguments)
    assert blocked_side_effects == ['opening a modal dialog (%s.%s)' % (owner.__name__, name)]
    assert dialogs_closed == []
    blocked_side_effects.clear()  # this test made the attempt on purpose


def test_a_static_dialog_inside_a_qt_slot_is_recorded(blocked_side_effects, dialogs_closed):
    button = W.QPushButton()
    button.clicked.connect(lambda: W.QMessageBox.warning(None, 'Title', 'Text'))
    button.click()  # Qt prints and swallows the exception raised inside the slot
    assert blocked_side_effects == ['opening a modal dialog (QMessageBox.warning)'] and dialogs_closed == []
    blocked_side_effects.clear()


def test_a_test_may_still_answer_a_static_dialog_itself(blocked_side_effects, dialogs_closed):
    from unittest.mock import patch
    with patch.object(W.QMessageBox, 'question', return_value=W.QMessageBox.Yes) as question:
        assert W.QMessageBox.question(None, 'Title', 'Text') == W.QMessageBox.Yes
    question.assert_called_once()
    assert blocked_side_effects == []
    with pytest.raises(AssertionError):
        W.QMessageBox.question(None, 'Title', 'Text')  # the guard is back once the test's own patch ends
    assert dialogs_closed == []
    blocked_side_effects.clear()


@pytest.mark.parametrize('owner', [W.QDialog, W.QMessageBox, W.QFileDialog])
@pytest.mark.parametrize('name', ['exec', 'exec_'])
def test_a_dialogs_own_exec_is_refused_under_either_name(blocked_side_effects, dialogs_closed, owner, name):
    dialog = owner()
    with pytest.raises(AssertionError, match='Forbidden in tests: opening a modal dialog'):
        getattr(dialog, name)()
    assert blocked_side_effects == ['opening a modal dialog'] and dialogs_closed == []
    blocked_side_effects.clear()
