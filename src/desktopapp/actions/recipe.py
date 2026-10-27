"""Worker jobs for the experimental PC Remote recipe writer.

recipe_plan only reads the camera. recipe_apply re-reads it, refuses unless the
plan is still exactly the one the user reviewed, then writes with read-back.
Neither needs administrator rights: PC Remote is a user-space USB interface.
"""
import dataclasses
from .. import recipes
from .catalog import RECIPE_ACTIONS

ACTIONS = RECIPE_ACTIONS
# What the user should know about the write in flight when apply() stopped. Chinese source
# strings like the rest of the interface; the window shows them through tr() (see localized).
OUTCOME_HINTS = {
    'unknown': '相机可能已执行、也可能未执行最后一次写入；请先重新读取相机，再做任何操作。',
    'not_applied': '相机接受了最后一次写入，但没有生效。',
    'rejected': '相机拒绝了最后一次写入。',
    'not_sent': '最后一次写入没有发出。',
}


def localized(error, tr):
    """A recipe job's error with its outcome hint in the interface language."""
    for hint in OUTCOME_HINTS.values():
        error = error.replace(hint, tr(hint))
    return error


def recipe_args(recipe):
    return dataclasses.asdict(recipe)


def recipe_from(args):
    return recipes.Recipe(**args['recipe'])


def signature(planned):
    """The plan's steps as JSON values, to compare the reviewed plan with a fresh one."""
    return [['write', step.code, step.value, step.provisional] if isinstance(step, recipes.Write)
            else ['reread', step.reason] for step in planned.steps]


def change(label, code, before, after, provisional):
    """One write as display values; before is None for a provisional write (re-read before writing)."""
    return dict(label=label, before=None if provisional else recipes.display_value(code, before),
                after=recipes.display_value(code, after), provisional=provisional)


def summary(planned):
    writes = [change(w.label, w.code, w.current, w.value, w.provisional) for w in planned.writes]
    return dict(ok=planned.ok, steps=signature(planned), writes=writes,
                problems=[dict(label=p.label, reason=p.reason, blocking=p.blocking) for p in planned.problems])


def consented(args):
    """Only a real True stops ptpcamerad, matching ptpremote's own `consent is not True` check."""
    return args.get('stop_ptpcamerad') is True


def open_session(args, *, ptp=None):
    if ptp is None:
        from camera_runtime import ptpremote as ptp
    transport = (ptp.claim_after_stopping_ptpcamerad(ptp.PyUsbTransport.open, consent=True)
                 if consented(args) else ptp.PyUsbTransport.open())
    return ptp.RemoteSession(transport)


def run(action, args, *, open_session=open_session):
    if action not in ACTIONS:
        raise ValueError('Unknown recipe action: ' + action)
    recipe = recipe_from(args)
    if action == 'recipe_apply' and not isinstance(args.get('reviewed'), list):
        raise ValueError('Writing a recipe needs the reviewed plan; read the camera first')
    with open_session(args) as camera:
        snapshot = camera.read_all()
        planned = recipes.plan(recipe, snapshot)
        if action == 'recipe_plan':
            return dict(summary(planned), recipe=args['recipe'], stop_ptpcamerad=consented(args),
                        camera_io='read_only')
        if signature(planned) != args['reviewed']:
            raise RuntimeError('The camera settings changed since you reviewed the plan; nothing was written. '
                               'Read the camera again.')
        try:
            result = recipes.apply(camera, planned, baseline=snapshot)
        except recipes.ApplyError as exc:
            raise RuntimeError('%s %s' % (exc, OUTCOME_HINTS.get(exc.outcome, ''))) from exc
    written = [change(row.write.label, row.write.code, row.before, row.after, False) for row in result.completed]
    return dict(written=written, recipe=args['recipe'],
                camera_io='written_and_verified')
