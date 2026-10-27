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
from .compilelook import DEFAULT_CALIBRATION
from .references import lattice

CALIBRATION = DEFAULT_CALIBRATION
# Colours per model evaluation. The measured model's TPS step allocates about
# 2.5 kB per colour per centre, so one pass over a 33^3 grid peaked near 5 GB;
# 1024-colour chunks peak near 0.4 GB and run no slower.
CHUNK = 1024
GAP = 16
# The exact model costs about 1 ms per colour, so photos are rendered through a
# grid of exact predictions. Against the exact model on a real look, 33 points per
# axis gave mean 0.10, p99 0.86 and max 2.8 8-bit levels (17: 0.31 / 1.83 / 5.9).
GRID = 33
EXIF_IFD, COLOR_SPACE, UNCALIBRATED = 0x8769, 0xA001, 0xFFFF  # how Sony marks Adobe RGB JPEGs


def load_model(path=CALIBRATION):
    from .measuredmodel import Response
    return Response(path)


def fitted_vector(document):
    """The compiler's fit vector: rounded table followed by the 17 quantized native controls."""
    table = lookfile.validate(document)
    controls = lookfile.native_controls(document)
    if controls is None:
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
    """Exact predictions on a size^3 lattice (values[b, g, r]); cached per look and model calibration."""
    vector = fitted_vector(document)
    path = None
    if cache is not None:
        calibration = CALIBRATION if model is None else Path(model.path)
        key = hashlib.sha256(vector.tobytes() + size.to_bytes(2, 'little') + calibration.read_bytes()).hexdigest()
        path = Path(cache) / (key + '.npy')
        if path.is_file():
            return np.load(path, allow_pickle=False)
    values = predict(document, lattice(size), model).reshape(size, size, size, 3)
    if path is not None:
        path.parent.mkdir(parents=True, exist_ok=True)
        # Each writer gets its own partial file, so two renders of one look cannot collide.
        handle, partial = tempfile.mkstemp(prefix=path.stem + '.', suffix='.partial.npy', dir=path.parent)
        os.close(handle)
        try:
            np.save(partial, values)
            os.replace(partial, path)
        finally:
            if os.path.exists(partial):
                os.remove(partial)
    return values


def source_kind(document):
    """'cube' or 'dcp' for the look's embedded source, or None when nothing is embedded."""
    if (document.get('source_reference') or {}).get('cube_base64'):
        return 'cube'
    return 'dcp' if document.get('raw_profile') else None


def source_rendering(document, rgb):
    """The look's own source (CUBE, through its bridge if any, or DCP) applied to ST colours, or None."""
    from .compilelook import cube_targets, dcp_targets
    rgb = np.asarray(rgb, float).reshape(-1, 3)
    kind = source_kind(document)
    with tempfile.TemporaryDirectory(prefix='a7c2-preview-') as temporary:
        if kind == 'cube':
            reference = document['source_reference']
            path = Path(temporary) / 'source.cube'
            path.write_bytes(base64.b64decode(reference['cube_base64'], validate=True))
            bridge = None
            if reference.get('bridge_base64'):
                bridge = Path(temporary) / 'bridge.cube'
                bridge.write_bytes(base64.b64decode(reference['bridge_base64'], validate=True))
            return cube_targets(rgb, path, reference.get('input_space'), bridge)[0]
        if kind == 'dcp':
            from .rawidentity import source_bytes
            path = Path(temporary) / 'source.dcp'
            path.write_bytes(source_bytes(document['raw_profile']))
            return dcp_targets(rgb, path)[0]
    return None


def srgb_photo(image, original):
    """(sRGB image, colour note) for an oriented photo. A photo whose ICC profile is not sRGB is
    converted; one marked uncalibrated without a profile is flagged, never guessed."""
    import io
    from PIL import ImageCms
    icc = original.info.get('icc_profile')
    if icc:
        profile = ImageCms.ImageCmsProfile(io.BytesIO(icc))
        name = ImageCms.getProfileDescription(profile).strip()
        if 'srgb' not in name.lower():
            try:
                converted = ImageCms.profileToProfile(image, profile, ImageCms.createProfile('sRGB'), outputMode='RGB')
            except ImageCms.PyCMSError as exc:
                raise ValueError('Cannot convert this photo from %s to sRGB: %s' % (name, exc)) from exc
            return converted, dict(kind='converted', profile=name)
    elif original.getexif().get_ifd(EXIF_IFD).get(COLOR_SPACE) == UNCALIBRATED:
        return image.convert('RGB'), dict(kind='uncalibrated')
    return image.convert('RGB'), None


def render(document, photo, output, *, max_side=1200, model=None, grid_size=GRID, cache=None):
    """Side-by-side photo / source look / predicted camera panels, saved as one PNG without text."""
    from PIL import Image, ImageOps
    from .references import Cube
    original = Image.open(photo)
    image, colour = srgb_photo(ImageOps.exif_transpose(original), original)
    image.thumbnail((max_side, max_side))
    pixels = np.asarray(image)
    flat = pixels.reshape(-1, 3) / 255
    panels = [dict(role='photo', pixels=pixels)]
    source = source_rendering(document, flat)
    if source is not None:
        panels.append(dict(role='source', kind=source_kind(document), pixels=to_bytes(source, pixels.shape)))
    camera = Cube.from_values(prediction_grid(document, size=grid_size, model=model, cache=cache))
    panels.append(dict(role='camera', pixels=to_bytes(camera.sample(flat), pixels.shape)))
    height, width = pixels.shape[:2]
    sheet = Image.new('RGB', (len(panels) * width + (len(panels) - 1) * GAP, height), 'white')
    for index, panel in enumerate(panels):
        sheet.paste(Image.fromarray(panel['pixels']), (index * (width + GAP), 0))
    sheet.save(output)
    return dict(output=str(output), panels=panels, colour=colour, camera_io=False)


def to_bytes(values, shape):
    return np.rint(np.clip(values, 0, 1) * 255).astype(np.uint8).reshape(shape)
