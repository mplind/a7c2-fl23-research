"""Offline preview of a compiled look on the user's own photo. Never opens a camera.

The camera panel uses the compiler's own measured model and the look's stored
table and native controls, so it is the same surrogate prediction the fit metrics
describe: an approximation, not a camera capture.
"""
import base64
import hashlib
import os
from pathlib import Path
import tempfile
import numpy as np
from . import lookfile, native, nativefit

ROOT = Path(__file__).resolve().parents[3]
CALIBRATION = ROOT / 'calibration/a7c2-2.01.virtual.npz'
CHUNK = 65536  # colours per model evaluation; bounds memory
GAP = 16
# The exact model costs about 1 ms per colour, so photos are rendered through a
# grid of exact predictions. Against the exact model on a real look, 33 points per
# axis gave mean 0.10, p99 0.86 and max 2.8 8-bit levels (17: 0.31 / 1.83 / 5.9).
GRID = 33


def load_model(path=CALIBRATION):
    from .measuredmodel import Response
    return Response(path)


def fitted_vector(document):
    """The compiler's fit vector: rounded table followed by the 17 quantized native controls."""
    table = lookfile.validate(document)
    controls = document.get('validation', {}).get('metrics', {}).get('native_controls')
    if not isinstance(controls, list) or len(controls) != 17:
        raise ValueError('This look has no fit data (native controls); preview needs a look compiled by this tool')
    return np.r_[np.asarray(native.decode(table), float).ravel(), np.asarray(controls, float)]


def predict(document, rgb, model=None):
    """Predicted in-camera sRGB for ST-rendered sRGB colours in 0..1, shape (N, 3)."""
    model = model or load_model()
    vector = fitted_vector(document)
    rgb = np.asarray(rgb, float).reshape(-1, 3)
    result = np.empty_like(rgb)
    for start in range(0, len(rgb), CHUNK):
        part = rgb[start:start + CHUNK]
        result[start:start + CHUNK] = nativefit.Problem(model, part, part, 1e-10).prediction(vector)
    return result


def prediction_grid(document, *, size=GRID, model=None, cache=None):
    """Exact predictions on a size^3 lattice (values[b, g, r]); cached per look and calibration."""
    vector = fitted_vector(document)
    key = hashlib.sha256(vector.tobytes() + size.to_bytes(2, 'little') + CALIBRATION.read_bytes()).hexdigest()
    path = Path(cache) / (key + '.npy') if cache is not None else None
    if path is not None and path.is_file():
        return np.load(path, allow_pickle=False)
    axis = np.linspace(0, 1, size)
    blue, green, red = np.meshgrid(axis, axis, axis, indexing='ij')
    lattice = np.stack([red.ravel(), green.ravel(), blue.ravel()], 1)
    values = predict(document, lattice, model).reshape(size, size, size, 3)
    if path is not None:
        path.parent.mkdir(parents=True, exist_ok=True)
        partial = path.with_suffix('.partial.npy')
        np.save(partial, values)
        os.replace(partial, path)
    return values


def source_rendering(document, rgb):
    """The look's own source (CUBE or DCP) applied to ST colours, or None when it is not embedded."""
    rgb = np.asarray(rgb, float).reshape(-1, 3)
    reference = document.get('source_reference') or {}
    with tempfile.TemporaryDirectory(prefix='a7c2-preview-') as temporary:
        if reference.get('cube_base64') and reference.get('input_space') == 'sony-st-srgb':
            from .references import Cube
            path = Path(temporary) / 'source.cube'
            path.write_bytes(base64.b64decode(reference['cube_base64'], validate=True))
            return np.clip(Cube(path).sample(rgb), 0, 1)
        if document.get('raw_profile'):
            from .compilelook import dcp_targets
            from .rawidentity import source_bytes
            path = Path(temporary) / 'source.dcp'
            path.write_bytes(source_bytes(document['raw_profile']))
            return dcp_targets(rgb, path)[0]
    return None


def render(document, photo, output, *, max_side=1200, model=None, grid_size=GRID, cache=None):
    """Side-by-side photo / source look / predicted camera panels, saved as one PNG without text."""
    from PIL import Image, ImageOps
    from .references import Cube
    image = ImageOps.exif_transpose(Image.open(photo)).convert('RGB')
    image.thumbnail((max_side, max_side))
    pixels = np.asarray(image)
    flat = pixels.reshape(-1, 3) / 255
    panels = [dict(role='photo', pixels=pixels)]
    source = source_rendering(document, flat)
    if source is not None:
        panels.append(dict(role='source', pixels=to_bytes(source, pixels.shape)))
    camera = Cube.from_values(prediction_grid(document, size=grid_size, model=model, cache=cache))
    panels.append(dict(role='camera', pixels=to_bytes(camera.sample(flat), pixels.shape)))
    height, width = pixels.shape[:2]
    sheet = Image.new('RGB', (len(panels) * width + (len(panels) - 1) * GAP, height), 'white')
    for index, panel in enumerate(panels):
        sheet.paste(Image.fromarray(panel['pixels']), (index * (width + GAP), 0))
    sheet.save(output)
    return dict(output=str(output), panels=panels, camera_io=False)


def to_bytes(values, shape):
    return np.rint(np.clip(values, 0, 1) * 255).astype(np.uint8).reshape(shape)
