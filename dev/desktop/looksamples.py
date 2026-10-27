"""Small compiled-look files for desktop tests; no camera access."""
import numpy as np
from looktool import lookfile, native


def look_file(path, *, mae=None, p95=None, name='Fixture'):
    """A valid .a7look with an all-zero table and, optionally, held-out fit metrics."""
    metrics = {} if mae is None else {'virtual_heldout_validation_replica': {'RGB_MAE_8bit': mae, 'RGB_P95_8bit': p95}}
    lookfile.write(path, name, native.encode(np.zeros((405, 3), int)), method='fixture', attribution='test', metrics=metrics)
    return path
