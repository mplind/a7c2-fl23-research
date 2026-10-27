"""Film recipe page: preset choice, read-only planning job, review dialog and reviewed write; no USB."""
import json
import os
from unittest.mock import Mock, patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import pytest
from PySide6 import QtWidgets as W
from desktopapp import i18n, jobs, recipes
from desktopapp.actions import recipe as job
from desktopapp.paths import write_json
from desktopapp.window import Window

HAN = __import__('re').compile('[㐀-鿿（），：；、。“”]')


@pytest.fixture
def window(tmp_path, monkeypatch):
    monkeypatch.setenv('A7C2_DESKTOP_DATA', str(tmp_path / 'data'))
    # No test may start a real worker, even when the code under test is wrong.
    monkeypatch.setattr('desktopapp.window.QtCore.QProcess', Mock())
    app = W.QApplication.instance() or W.QApplication([])
    windows = []
    def create(language=None, platform=None):
        if language:
            write_json(tmp_path / 'data/desktop.json', {'language': language})
        with patch('desktopapp.window.sys.platform', platform or 'darwin'):
            result = Window()
        result.timer.stop(); windows.append(result)
        return result
    yield create
    for result in windows:
        result.process = None; result.close()
    i18n.configure('zh_CN')


def requested(ui):
    return json.loads((ui.current_job / 'request.private.json').read_text())


def test_the_page_offers_every_preset_with_its_source_and_values(window):
    ui = window('en')
    assert ui.nav.item(7).text() == 'Film recipes (experimental)'
    assert [ui.recipe_preset.itemText(i) for i in range(ui.recipe_preset.count())] == [p.name for p in recipes.PRESETS]
    ui.recipe_preset.setCurrentIndex([p.name for p in recipes.PRESETS].index('Vintage Chrome'))
    details = ui.recipe_details.text()
    for text in ('FL3', 'Contrast -2', 'Sharpness Range 3', 'WB shift A4 · G1.75', recipes.SONY_SINGAPORE):
        assert text in details


def test_reading_the_camera_starts_a_read_only_plan_job_with_the_chosen_slot(window):
    ui = window()
    ui.recipe_preset.setCurrentIndex(1); ui.recipe_target.setCurrentIndex(3)
    with patch('desktopapp.window.QtCore.QProcess'), patch.object(W.QMessageBox, 'question') as asked:
        ui.recipe_button.click()
    asked.assert_not_called()  # reading is not a write: no confirmation, no power check
    request = requested(ui)
    assert request['action'] == 'recipe_plan'
    assert job.recipe_from(request['arguments']) == recipes.Recipe(**dict(job.recipe_args(recipes.PRESETS[1]), target=3))
    assert request['arguments']['stop_ptpcamerad'] is False
    assert ui.camera_operation and not ui.stop.isEnabled()


def test_the_ptpcamerad_consent_is_passed_only_when_ticked(window):
    ui = window()
    ui.recipe_ptpcamerad.setChecked(True)
    with patch('desktopapp.window.QtCore.QProcess'):
        ui.recipe_button.click()
    assert requested(ui)['arguments']['stop_ptpcamerad'] is True


def finish(ui, action, result=None, error=None):
    ui.current_job = jobs.new_job(action, {})
    status = dict(phase='SUCCEEDED', action=action, result=result) if error is None else \
        dict(phase='FAILED', action=action, error=error)
    write_json(ui.current_job / 'status.private.json', status)
    ui.process = Mock()
    ui.finished(0 if error is None else 2, None)


def plan_result(**changes):
    value = dict(ok=True, steps=[['write', 0xD0FA, 6, False], ['reread', 'Creative Look selection changed'],
                                 ['write', 0xD0FB, -2, True]],
                 writes=[dict(label='Creative Look', before='ST', after='FL', provisional=False),
                         dict(label='Contrast', before=None, after='-2', provisional=True)],
                 problems=[dict(label='Position Key', reason='not offered', blocking=False)], unchanged=[],
                 recipe=job.recipe_args(recipes.PRESETS[0]), stop_ptpcamerad=True, camera_io='read_only')
    value.update(changes)
    return value


def test_a_reviewed_plan_is_written_only_after_yes_with_the_exact_reviewed_steps(window):
    ui = window('en')
    with patch.object(W.QMessageBox, 'question', return_value=W.QMessageBox.Yes) as asked, \
            patch('desktopapp.window.QtCore.QProcess'):
        finish(ui, 'recipe_plan', plan_result())
    title, text = asked.call_args.args[1:3]
    assert title == 'Write recipe (experimental)'
    assert '• Creative Look: ST → FL' in text and 'Position Key: not offered' in text and 'not been tested' in text
    assert text.index('After the look or white balance switches') < text.index('• Contrast: -2')
    assert 'This writes 2 camera settings' in text
    assert not HAN.search(title + text)
    request = requested(ui)
    assert request['action'] == 'recipe_apply'
    assert request['arguments'] == dict(recipe=plan_result()['recipe'], stop_ptpcamerad=True,
                                        reviewed=plan_result()['steps'])


def test_cancelling_the_review_writes_nothing(window):
    ui = window()
    with patch.object(W.QMessageBox, 'question', return_value=W.QMessageBox.Cancel), \
            patch.object(jobs, 'new_job', wraps=jobs.new_job) as new:
        finish(ui, 'recipe_plan', plan_result())
    assert [call.args[0] for call in new.call_args_list] == ['recipe_plan']
    assert ui.process is None


def test_a_blocked_plan_explains_why_and_offers_no_write(window):
    ui = window('en')
    blocked = plan_result(ok=False, problems=[dict(label='Picture Profile', reason='PP3 is on', blocking=True)])
    with patch.object(W.QMessageBox, 'warning') as warned, patch.object(W.QMessageBox, 'question') as asked:
        finish(ui, 'recipe_plan', blocked)
    asked.assert_not_called()
    assert 'Picture Profile: PP3 is on' in warned.call_args.args[2]


def test_a_camera_that_already_matches_needs_no_write(window):
    ui = window()
    with patch.object(W.QMessageBox, 'information') as told, patch.object(W.QMessageBox, 'question') as asked:
        finish(ui, 'recipe_plan', plan_result(writes=[], steps=[]))
    asked.assert_not_called(); told.assert_called_once()


def test_a_finished_write_lists_what_was_verified(window):
    ui = window('en')
    with patch.object(W.QMessageBox, 'information') as told:
        finish(ui, 'recipe_apply', dict(written=[dict(label='Contrast', before='0', after='-2', provisional=False)],
                                        recipe={}, camera_io='written_and_verified'))
    assert '• Contrast: 0 → -2' in told.call_args.args[2]
    assert ui.status.text() == 'Recipe written and read back.'


def test_a_failed_write_shows_the_worker_error(window):
    ui = window('en')
    finish(ui, 'recipe_apply', error='Stopped at Contrast: timeout. The camera may or may not have applied the last write.')
    assert 'may or may not have applied' in ui.status.text()


def test_windows_explains_the_missing_driver_and_disables_reading(window):
    ui = window('en', platform='win32')
    assert not ui.recipe_button.isEnabled()
    assert 'WinUSB' in ui.recipe_windows_note.text()
    assert ui.recipe_ptpcamerad.isHidden()


def test_the_english_page_shows_no_chinese(window):
    ui = window('en')
    ui.nav.setCurrentRow(7)
    page = ui.pages.widget(7)
    texts = [w.text() for kind in (W.QLabel, W.QAbstractButton) for w in page.findChildren(kind)] + \
            [ui.recipe_target.itemText(i) for i in range(ui.recipe_target.count())]
    assert not any(HAN.search(text) for text in texts)
