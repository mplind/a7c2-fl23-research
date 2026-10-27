"""Worker jobs for the experimental PC Remote recipe writer, against the fake body; no USB."""
import dataclasses
from types import SimpleNamespace
from unittest.mock import Mock
import pytest
from desktopapp import jobs, recipes
from desktopapp.actions import recipe as job
from test_ptpremote import session_for
from test_recipes import Body


def opener(body):
    return lambda args: session_for(body.camera)[0]


def request(preset='Retro Negative', **changes):
    return dict(recipe=job.recipe_args(dataclasses.replace(recipes.preset(preset), **changes)), stop_ptpcamerad=False)


def test_recipe_arguments_round_trip_through_json_types():
    for preset in recipes.PRESETS:
        assert job.recipe_from(dict(recipe=job.recipe_args(preset))) == preset


def test_plan_reads_the_camera_and_writes_nothing():
    body = Body()
    result = job.run('recipe_plan', request(), open_session=opener(body))
    assert 0x9205 not in body.camera.opcodes and body.camera.writes() == []
    assert result['ok'] and result['camera_io'] == 'read_only'
    assert dict(label='Creative Look', before='ST', after='FL', provisional=False) in result['writes']
    assert dict(label='Contrast', before=None, after='-2', provisional=True) in result['writes']
    assert result['recipe'] == request()['recipe'] and result['stop_ptpcamerad'] is False
    assert ['reread', 'Creative Look selection changed'] in result['steps']
    assert 'unchanged' not in result


def test_plan_reports_blockers_without_writing():
    body = Body(picture_profile=3)
    result = job.run('recipe_plan', request(), open_session=opener(body))
    assert not result['ok'] and body.camera.writes() == []
    assert any(p['blocking'] and p['label'] == 'Picture Profile' for p in result['problems'])


def test_apply_writes_the_reviewed_plan_and_reports_each_verified_write():
    body = Body()
    reviewed = job.run('recipe_plan', request(target=4), open_session=opener(body))
    result = job.run('recipe_apply', dict(request(target=4), reviewed=reviewed['steps']), open_session=opener(body))
    assert body.prop(0xD0FA).current == 0x0104 and body.prop(0xD103).current == recipes.BASE_LOOKS['FL']
    assert body.prop(0xD0FB).current == -2
    assert len(result['written']) == len(body.camera.writes())
    assert dict(label='Creative Look', before='ST', after='Custom Look 4', provisional=False) in result['written']
    assert dict(label='Contrast', before='0', after='-2', provisional=False) in result['written']
    assert result['camera_io'] == 'written_and_verified'


def test_apply_refuses_when_the_camera_changed_since_review():
    body = Body()
    reviewed = job.run('recipe_plan', request(), open_session=opener(body))
    body.prop(0xD0FA).current = recipes.BASE_LOOKS['FL']  # someone changed the look on the camera in between
    body.load_look()
    with pytest.raises(RuntimeError, match='changed since you reviewed'):
        job.run('recipe_apply', dict(request(), reviewed=reviewed['steps']), open_session=opener(body))
    assert body.camera.writes() == []


def test_apply_needs_a_reviewed_plan():
    with pytest.raises(ValueError, match='reviewed'):
        job.run('recipe_apply', request(), open_session=opener(Body()))


@pytest.mark.parametrize('outcome', ['unknown', 'not_applied', 'rejected', 'not_sent'])
def test_a_stopped_apply_explains_what_the_last_write_did(monkeypatch, outcome):
    body = Body()
    reviewed = job.run('recipe_plan', request(), open_session=opener(body))
    def stopped(session, planned, baseline=None):
        raise recipes.ApplyError('Stopped at Contrast: 0 → -2: timeout.', outcome=outcome)
    monkeypatch.setattr(recipes, 'apply', stopped)
    with pytest.raises(RuntimeError) as raised:
        job.run('recipe_apply', dict(request(), reviewed=reviewed['steps']), open_session=opener(body))
    assert 'Stopped at Contrast' in str(raised.value) and job.OUTCOME_HINTS[outcome] in str(raised.value)


def test_every_outcome_hint_has_an_english_entry():
    from desktopapp.en import STRINGS
    assert all(hint in STRINGS for hint in job.OUTCOME_HINTS.values())
    assert job.localized('x ' + job.OUTCOME_HINTS['unknown'], lambda text: STRINGS.get(text, text)) == \
        'x ' + STRINGS[job.OUTCOME_HINTS['unknown']]


def test_apply_reads_the_whole_camera_once_before_its_first_write():
    body = Body()
    reviewed = job.run('recipe_plan', request(), open_session=opener(body))
    body.camera.commands.clear()
    job.run('recipe_apply', dict(request(), reviewed=reviewed['steps']), open_session=opener(body))
    opcodes = body.camera.opcodes
    assert opcodes[:opcodes.index(0x9205)].count(0x9209) == 1


@pytest.mark.parametrize('value', ['false', 'no', 1, 'yes'])
def test_only_a_real_true_counts_as_consent_to_stop_ptpcamerad(value):
    ptp = SimpleNamespace(PyUsbTransport=SimpleNamespace(open=Mock(return_value='transport')),
                          claim_after_stopping_ptpcamerad=Mock(), RemoteSession=Mock())
    job.open_session(dict(stop_ptpcamerad=value), ptp=ptp)
    ptp.claim_after_stopping_ptpcamerad.assert_not_called()
    ptp.PyUsbTransport.open.assert_called_once_with()


def test_the_default_opener_stops_ptpcamerad_only_with_consent():
    transport = object()
    ptp = SimpleNamespace(PyUsbTransport=SimpleNamespace(open=Mock(return_value=transport)),
                          claim_after_stopping_ptpcamerad=Mock(return_value=transport),
                          RemoteSession=Mock(side_effect=lambda t: ('session', t)))
    assert job.open_session(dict(stop_ptpcamerad=False), ptp=ptp) == ('session', transport)
    ptp.claim_after_stopping_ptpcamerad.assert_not_called()
    assert job.open_session(dict(stop_ptpcamerad=True), ptp=ptp) == ('session', transport)
    ptp.claim_after_stopping_ptpcamerad.assert_called_once_with(ptp.PyUsbTransport.open, consent=True)


def test_recipe_jobs_never_ask_for_administrator_rights_or_power_confirmation():
    for action in job.ACTIONS:
        assert action in jobs.REMOTE_ACTIONS
        assert action not in jobs.CAMERA_ACTIONS and action not in jobs.POWER_ACTIONS


def test_the_worker_dispatches_every_recipe_job(monkeypatch, tmp_path):
    from desktopapp import worker
    seen = []
    monkeypatch.setattr(job, 'run', lambda action, args: seen.append((action, args)) or {'ok': True})
    for action in job.ACTIONS:
        assert worker.run(action, {'recipe': {}}, tmp_path) == {'ok': True}
    assert [action for action, _ in seen] == list(job.ACTIONS) == ['recipe_plan', 'recipe_apply']
