"""Offline look preview on a user's photo; never opens a camera."""
import base64
from pathlib import Path
from types import SimpleNamespace
import numpy as np
from PIL import Image, ImageCms
import pytest
from looktool import compilelook, lookfile, lookpreview, native, nativefit, photomeasure, rawidentity
from looktool.references import Cube, lattice
from test_compile_dcp_offline import dcp

RNG = np.random.default_rng(7)
ADOBE_RGB = Path('/System/Library/ColorSync/Profiles/AdobeRGB1998.icc')


@pytest.fixture(scope='module')
def model():
    return lookpreview.load_model()


def cube_text(size, function):
    axis = np.linspace(0, 1, size)
    rows = ['LUT_3D_SIZE %d' % size]
    for b in axis:
        for g in axis:
            for r in axis:
                rows.append('%.6f %.6f %.6f' % tuple(function(np.array([r, g, b]))))
    return '\n'.join(rows) + '\n'


def compiled_look(tmp_path, *, table=None, controls=None, cube=None, input_space='sony-st-srgb', bridge=None,
                  raw_profile=None, name='Fixture'):
    table = RNG.integers(-20, 21, size=(405, 3)) if table is None else table
    controls = list(photomeasure.quantized(RNG.uniform(-.5, .5, 17))) if controls is None else controls
    metrics = {} if controls is False else {'native_controls': controls}
    reference = None if cube is None else {'schema': 'a7c2-source-cube/1', 'filename': 'fixture.cube',
        'input_space': input_space, 'cube_base64': base64.b64encode(cube.encode()).decode()}
    if bridge is not None:
        reference['bridge_base64'] = base64.b64encode(bridge.encode()).decode()
    path = tmp_path / (name + '.a7look')
    lookfile.write(path, name, native.encode(table), method='fixture', attribution='test',
                   metrics=metrics, source_reference=reference, raw_profile=raw_profile)
    return lookfile.read(path), table, controls


def test_prediction_matches_the_compilers_own_model_exactly(tmp_path, model):
    document, table, controls = compiled_look(tmp_path)
    colours = RNG.uniform(.03, .97, (300, 3))
    vector = np.r_[table.ravel().astype(float), controls]
    expected = nativefit.Problem(model, colours, colours, 1e-10).prediction(vector)
    assert np.array_equal(lookpreview.predict(document, colours, model=model), expected)


def test_prediction_is_identical_across_chunk_boundaries(tmp_path, model, monkeypatch):
    document, _, _ = compiled_look(tmp_path)
    colours = RNG.uniform(.03, .97, (250, 3))
    whole = lookpreview.predict(document, colours, model=model)
    monkeypatch.setattr(lookpreview, 'CHUNK', 64)
    assert np.array_equal(lookpreview.predict(document, colours, model=model), whole)


class Recorder:
    """Stands in for nativefit.Problem: records chunk sizes and predicts the model's constant."""
    sizes = []

    def __init__(self, model, source, target, smooth):
        self.model, self.count = model, len(source)
        Recorder.sizes.append(self.count)

    def prediction(self, vector):
        return np.full((self.count, 3), self.model.value)


def fake_model(tmp_path, value, name):
    path = tmp_path / name
    path.write_bytes(name.encode())
    return SimpleNamespace(path=path, value=value)


def test_the_default_grid_is_evaluated_in_small_chunks(tmp_path, monkeypatch):
    # One pass over all 33^3 colours peaked near 5 GB in the measured model's TPS step.
    document, _, _ = compiled_look(tmp_path)
    monkeypatch.setattr(lookpreview.nativefit, 'Problem', Recorder)
    Recorder.sizes = []
    lookpreview.prediction_grid(document, model=fake_model(tmp_path, .5, 'model.npz'))
    assert sum(Recorder.sizes) == lookpreview.GRID ** 3 and max(Recorder.sizes) <= 1024


def test_the_cache_is_keyed_on_the_model_actually_used(tmp_path, monkeypatch):
    document, _, _ = compiled_look(tmp_path)
    monkeypatch.setattr(lookpreview.nativefit, 'Problem', Recorder)
    first = lookpreview.prediction_grid(document, size=3, model=fake_model(tmp_path, .2, 'a.npz'), cache=tmp_path / 'c')
    second = lookpreview.prediction_grid(document, size=3, model=fake_model(tmp_path, .7, 'b.npz'), cache=tmp_path / 'c')
    assert np.allclose(first, .2) and np.allclose(second, .7)


def test_concurrent_cache_writers_use_their_own_partial_files(tmp_path, monkeypatch):
    document, _, _ = compiled_look(tmp_path)
    monkeypatch.setattr(lookpreview.nativefit, 'Problem', Recorder)
    saved = []
    original = np.save
    monkeypatch.setattr(lookpreview.np, 'save', lambda path, values: saved.append(Path(path)) or original(path, values))
    model = fake_model(tmp_path, .3, 'a.npz')
    for _ in range(2):
        lookpreview.prediction_grid(document, size=3, model=model, cache=tmp_path / 'c')
        for cached in (tmp_path / 'c').glob('*.npy'):
            cached.unlink()  # force the second call to write again
    assert len(saved) == 2 and saved[0] != saved[1]


def test_a_look_without_fit_data_is_rejected(tmp_path, model):
    document, _, _ = compiled_look(tmp_path, controls=False)
    with pytest.raises(ValueError, match='fit data'):
        lookpreview.predict(document, np.full((4, 3), .5), model=model)


@pytest.mark.parametrize('validation', [{'metrics': None}, None, {'metrics': {'native_controls': [0] * 16}},
                                        {'metrics': {'native_controls': [float('nan')] * 17}}])
def test_malformed_fit_data_is_reported_as_missing(tmp_path, validation):
    document, _, _ = compiled_look(tmp_path)
    document['validation'] = validation
    assert lookfile.native_controls(document) is None
    with pytest.raises(ValueError, match='fit data'):
        lookpreview.fitted_vector(document)


@pytest.mark.parametrize('function,expected', [
    (lambda rgb: rgb, lambda rgb: rgb),
    (lambda rgb: 1 - rgb, lambda rgb: 1 - rgb),
])
def test_embedded_source_cube_is_rendered(tmp_path, function, expected):
    document, _, _ = compiled_look(tmp_path, cube=cube_text(5, function))
    colours = RNG.uniform(0, 1, (100, 3))
    assert np.allclose(lookpreview.source_rendering(document, colours), expected(colours), atol=1e-6)
    assert lookpreview.source_kind(document) == 'cube'


def test_a_bridged_cube_is_rendered_through_its_bridge(tmp_path):
    document, _, _ = compiled_look(tmp_path, cube=cube_text(5, lambda rgb: rgb ** 2), input_space='acescct',
                                   bridge=cube_text(5, lambda rgb: 1 - rgb))
    colours = RNG.uniform(0, 1, (100, 3))
    assert np.allclose(lookpreview.source_rendering(document, colours), (1 - colours) ** 2, atol=.02)
    assert lookpreview.source_kind(document) == 'cube'


def test_a_dcp_source_is_rendered_with_the_compilers_dcp_stage(tmp_path):
    profile = rawidentity.descriptor(dcp(tmp_path / 'fixture.dcp'))
    document, _, _ = compiled_look(tmp_path, raw_profile=profile)
    colours = RNG.uniform(.05, .95, (50, 3))
    expected = compilelook.dcp_targets(colours, tmp_path / 'fixture.dcp')[0]
    assert np.allclose(lookpreview.source_rendering(document, colours), expected)
    assert lookpreview.source_kind(document) == 'dcp'


def test_a_look_without_an_embedded_source_has_no_source_rendering(tmp_path):
    document, _, _ = compiled_look(tmp_path)
    assert lookpreview.source_rendering(document, np.full((2, 3), .5)) is None
    assert lookpreview.source_kind(document) is None


def test_prediction_grid_matches_the_exact_model_at_every_lattice_point(tmp_path, model):
    document, _, _ = compiled_look(tmp_path)
    grid = lookpreview.prediction_grid(document, size=4, model=model)
    axis = np.linspace(0, 1, 4)
    blue, green, red = np.meshgrid(axis, axis, axis, indexing='ij')
    expected_lattice = np.stack([red.ravel(), green.ravel(), blue.ravel()], 1)  # red varies fastest, as in .cube
    assert np.array_equal(lattice(4), expected_lattice)
    assert grid.shape == (4, 4, 4, 3)
    assert np.array_equal(grid.reshape(-1, 3), lookpreview.predict(document, expected_lattice, model=model))


def test_a_cached_grid_is_reused_without_loading_the_model(tmp_path, model, monkeypatch):
    document, _, _ = compiled_look(tmp_path)
    first = lookpreview.prediction_grid(document, size=3, model=model, cache=tmp_path / 'cache')
    with monkeypatch.context() as patched:  # undo only this patch, not the suite's guards
        patched.setattr(lookpreview, 'load_model', lambda *a: pytest.fail('model loaded despite cache'))
        assert np.array_equal(lookpreview.prediction_grid(document, size=3, cache=tmp_path / 'cache'), first)
    other, _, _ = compiled_look(tmp_path, name='Other')
    assert not np.array_equal(lookpreview.prediction_grid(other, size=3, model=model, cache=tmp_path / 'cache'), first)


def test_an_in_memory_cube_samples_exactly_like_the_same_cube_file(tmp_path):
    values = RNG.uniform(0, 1, (5, 5, 5, 3))
    path = tmp_path / 'grid.cube'
    path.write_text('LUT_3D_SIZE 5\n' + ''.join('%r %r %r\n' % tuple(map(float, v)) for v in values.reshape(-1, 3)))
    colours = RNG.uniform(0, 1, (200, 3))
    assert np.array_equal(Cube.from_values(values).sample(colours), Cube(path).sample(colours))


def write_photo(path, width=48, height=32, **save):
    x = np.linspace(0, 255, width, dtype=np.uint8)
    image = np.stack([np.tile(x, (height, 1)), np.tile(x[::-1], (height, 1)), np.full((height, width), 128, np.uint8)], -1)
    Image.fromarray(image).save(path, **save)
    return image


def test_render_returns_photo_source_and_prediction_panels(tmp_path, model):
    document, _, _ = compiled_look(tmp_path, cube=cube_text(3, lambda rgb: rgb))
    original = write_photo(tmp_path / 'shot.png')
    result = lookpreview.render(document, tmp_path / 'shot.png', tmp_path / 'preview.png', model=model, grid_size=4)
    assert [panel['role'] for panel in result['panels']] == ['photo', 'source', 'camera']
    assert result['panels'][1]['kind'] == 'cube' and result['colour'] is None
    assert np.array_equal(result['panels'][0]['pixels'], original)
    for panel in result['panels']:
        assert panel['pixels'].shape == original.shape and panel['pixels'].dtype == np.uint8
    saved = np.asarray(Image.open(result['output']))
    assert saved.shape[0] == original.shape[0] and saved.shape[1] == 3 * original.shape[1] + 2 * lookpreview.GAP


def test_render_downsizes_large_photos_and_skips_a_missing_source(tmp_path, model):
    document, _, _ = compiled_look(tmp_path)
    write_photo(tmp_path / 'large.png', width=300, height=200)
    result = lookpreview.render(document, tmp_path / 'large.png', tmp_path / 'preview.png', max_side=150, model=model, grid_size=4)
    assert [panel['role'] for panel in result['panels']] == ['photo', 'camera']
    assert result['panels'][0]['pixels'].shape == (100, 150, 3)


def test_render_draws_the_camera_panel_from_the_prediction_grid(tmp_path, model):
    document, _, _ = compiled_look(tmp_path)
    original = write_photo(tmp_path / 'shot.png')
    result = lookpreview.render(document, tmp_path / 'shot.png', tmp_path / 'preview.png', model=model, grid_size=4)
    grid = Cube.from_values(lookpreview.prediction_grid(document, size=4, model=model))
    expected = lookpreview.to_bytes(grid.sample(original.reshape(-1, 3) / 255), original.shape)
    assert np.array_equal(result['panels'][-1]['pixels'], expected)


@pytest.mark.skipif(not ADOBE_RGB.is_file(), reason='needs the macOS Adobe RGB profile')
def test_a_photo_with_another_icc_profile_is_converted_to_srgb(tmp_path, model):
    document, _, _ = compiled_look(tmp_path)
    original = write_photo(tmp_path / 'adobe.png', icc_profile=ADOBE_RGB.read_bytes())
    result = lookpreview.render(document, tmp_path / 'adobe.png', tmp_path / 'preview.png', model=model, grid_size=4)
    converted = ImageCms.profileToProfile(Image.fromarray(original), ImageCms.ImageCmsProfile(str(ADOBE_RGB)),
                                          ImageCms.createProfile('sRGB'), outputMode='RGB')
    assert np.array_equal(result['panels'][0]['pixels'], np.asarray(converted))
    assert result['colour'] == {'kind': 'converted', 'profile': ImageCms.getProfileDescription(
        ImageCms.ImageCmsProfile(str(ADOBE_RGB))).strip()}


def test_a_photo_marked_uncalibrated_without_a_profile_is_flagged(tmp_path, model):
    document, _, _ = compiled_look(tmp_path)
    exif = Image.Exif()
    exif.get_ifd(0x8769)[0xA001] = 0xFFFF  # ColorSpace: uncalibrated, how Sony marks Adobe RGB JPEGs
    write_photo(tmp_path / 'adobe.jpg', exif=exif, quality=95)
    result = lookpreview.render(document, tmp_path / 'adobe.jpg', tmp_path / 'preview.png', model=model, grid_size=4)
    assert result['colour'] == {'kind': 'uncalibrated'}
