"""Small compiled-look files for desktop tests; no camera access."""
import numpy as np
from looktool import lookfile, native


def look_file(path, *, mae=None, p95=None, name='Fixture', controls=True):
    """A valid .a7look with an all-zero table, optionally held-out fit metrics, and (unless
    controls=False) the 17 fitted native controls a preview needs."""
    metrics = {} if mae is None else {'virtual_heldout_validation_replica': {'RGB_MAE_8bit': mae, 'RGB_P95_8bit': p95}}
    if controls:
        metrics['native_controls'] = [0.0] * 17
    lookfile.write(path, name, native.encode(np.zeros((405, 3), int)), method='fixture', attribution='test', metrics=metrics)
    return path
