"""Worker jobs for the experimental PC Remote recipe writer.

recipe_plan only reads the camera. recipe_apply re-reads it, refuses unless the
plan is still exactly the one the user reviewed, then writes with read-back.
Neither needs administrator rights: PC Remote is a user-space USB interface.
"""
import dataclasses
from .. import recipes

ACTIONS = ('recipe_plan', 'recipe_apply')
# What the user should know about the write in flight when apply() stopped.
OUTCOME_HINTS = {
    'unknown': 'The camera may or may not have applied the last write; read the camera again before anything else.',
    'not_applied': 'The camera accepted the last write but did not apply it.',
    'rejected': 'The camera refused the last write.',
    'not_sent': 'The last write was not sent.',
}


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
                problems=[dict(label=p.label, reason=p.reason, blocking=p.blocking) for p in planned.problems],
                unchanged=[[recipes.LABELS[code], recipes.display_value(code, value)] for code, value in planned.unchanged])


def open_session(args, *, ptp=None):
    if ptp is None:
        from camera_runtime import ptpremote as ptp
    transport = (ptp.claim_after_stopping_ptpcamerad(ptp.PyUsbTransport.open, consent=True)
                 if args.get('stop_ptpcamerad') else ptp.PyUsbTransport.open())
    return ptp.RemoteSession(transport)


def run(action, args, *, open_session=open_session):
    if action not in ACTIONS:
        raise ValueError('Unknown recipe action: ' + action)
    recipe = recipe_from(args)
    if action == 'recipe_apply' and not isinstance(args.get('reviewed'), list):
        raise ValueError('Writing a recipe needs the reviewed plan; read the camera first')
    with open_session(args) as camera:
        planned = recipes.plan(recipe, camera.read_all())
        if action == 'recipe_plan':
            return dict(summary(planned), recipe=args['recipe'], stop_ptpcamerad=bool(args.get('stop_ptpcamerad')),
                        camera_io='read_only')
        if signature(planned) != args['reviewed']:
            raise RuntimeError('The camera settings changed since you reviewed the plan; nothing was written. '
                               'Read the camera again.')
        try:
            result = recipes.apply(camera, planned)
        except recipes.ApplyError as exc:
            raise RuntimeError('%s %s' % (exc, OUTCOME_HINTS.get(exc.outcome, ''))) from exc
    written = [change(row.write.label, row.write.code, row.before, row.after, False) for row in result.completed]
    return dict(written=written, recipe=args['recipe'],
                camera_io='written_and_verified')
