"""Shared helpers for the desktop GUI tests; no camera access."""
import re
from unittest.mock import Mock
from desktopapp import jobs
from desktopapp.paths import write_json

# Han characters and full-width punctuation: none may appear in the English interface.
HAN = re.compile('[㐀-鿿（），：；、。“”]')


def finish_job(window, action, result=None, error=None):
    """Let window.finished() handle a worker job that succeeded with result or failed with error."""
    window.current_job = jobs.new_job(action, {})
    status = dict(phase='SUCCEEDED', action=action, result=result) if error is None else \
        dict(phase='FAILED', action=action, error=error)
    write_json(window.current_job / 'status.private.json', status)
    window.process = Mock()
    window.finished(0 if error is None else 2, None)
