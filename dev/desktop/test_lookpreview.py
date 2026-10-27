"""Offline look preview on a user's photo; never opens a camera."""
import base64
import json
from pathlib import Path
import numpy as np
from PIL import Image
import pytest
from looktool import lookfile, lookpreview, native, nativefit, photomeasure

RNG = np.random.default_rng(7)


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


def compiled_look(tmp_path, *, table=None, controls=None, cube=None, name='Fixture'):
    table = RNG.integers(-20, 21, size=(405, 3)) if table is None else table
    controls = list(photomeasure.quantized(RNG.uniform(-.5, .5, 17))) if controls is None else controls
    metrics = {} if controls is False else {'native_controls': controls}
    reference = None if cube is None else {'schema': 'a7c2-source-cube/1', 'filename': 'fixture.cube',
        'input_space': 'sony-st-srgb', 'cube_base64': base64.b64encode(cube.encode()).decode()}
    path = tmp_path / (name + '.a7look')
    lookfile.write(path, name, native.encode(table), method='fixture', attribution='test',
                   metrics=metrics, source_reference=reference)
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


def test_a_look_without_fit_data_is_rejected(tmp_path, model):
    document, _, _ = compiled_look(tmp_path, controls=False)
    with pytest.raises(ValueError, match='fit data'):
        lookpreview.predict(document, np.full((4, 3), .5), model=model)


@pytest.mark.parametrize('function,expected', [
    (lambda rgb: rgb, lambda rgb: rgb),
    (lambda rgb: 1 - rgb, lambda rgb: 1 - rgb),
])
def test_embedded_source_cube_is_rendered(tmp_path, function, expected):
    document, _, _ = compiled_look(tmp_path, cube=cube_text(5, function))
    colours = RNG.uniform(0, 1, (100, 3))
    assert np.allclose(lookpreview.source_rendering(document, colours), expected(colours), atol=1e-6)


def test_a_look_without_an_embedded_source_has_no_source_rendering(tmp_path):
    document, _, _ = compiled_look(tmp_path)
    assert lookpreview.source_rendering(document, np.full((2, 3), .5)) is None


def test_prediction_grid_matches_the_exact_model_at_every_lattice_point(tmp_path, model):
    document, _, _ = compiled_look(tmp_path)
    grid = lookpreview.prediction_grid(document, size=4, model=model)
    axis = np.linspace(0, 1, 4)
    blue, green, red = np.meshgrid(axis, axis, axis, indexing='ij')
    lattice = np.stack([red.ravel(), green.ravel(), blue.ravel()], 1)  # red varies fastest, as in .cube
    assert grid.shape == (4, 4, 4, 3)
    assert np.array_equal(grid.reshape(-1, 3), lookpreview.predict(document, lattice, model=model))


def test_a_cached_grid_is_reused_without_loading_the_model(tmp_path, model, monkeypatch):
    document, _, _ = compiled_look(tmp_path)
    first = lookpreview.prediction_grid(document, size=3, model=model, cache=tmp_path / 'cache')
    monkeypatch.setattr(lookpreview, 'load_model', lambda *a: pytest.fail('model loaded despite cache'))
    assert np.array_equal(lookpreview.prediction_grid(document, size=3, cache=tmp_path / 'cache'), first)
    other, _, _ = compiled_look(tmp_path, name='Other')
    monkeypatch.undo()
    assert not np.array_equal(lookpreview.prediction_grid(other, size=3, model=model, cache=tmp_path / 'cache'), first)


def test_an_in_memory_cube_samples_exactly_like_the_same_cube_file(tmp_path):
    from looktool.references import Cube
    values = RNG.uniform(0, 1, (5, 5, 5, 3))
    path = tmp_path / 'grid.cube'
    path.write_text('LUT_3D_SIZE 5\n' + ''.join('%r %r %r\n' % tuple(map(float, v)) for v in values.reshape(-1, 3)))
    colours = RNG.uniform(0, 1, (200, 3))
    assert np.array_equal(Cube.from_values(values).sample(colours), Cube(path).sample(colours))


def write_photo(path, width=48, height=32):
    x = np.linspace(0, 255, width, dtype=np.uint8)
    image = np.stack([np.tile(x, (height, 1)), np.tile(x[::-1], (height, 1)), np.full((height, width), 128, np.uint8)], -1)
    Image.fromarray(image).save(path)
    return image


def test_render_returns_photo_source_and_prediction_panels(tmp_path, model):
    document, _, _ = compiled_look(tmp_path, cube=cube_text(3, lambda rgb: rgb))
    original = write_photo(tmp_path / 'shot.png')
    result = lookpreview.render(document, tmp_path / 'shot.png', tmp_path / 'preview.png', model=model, grid_size=4)
    assert [panel['role'] for panel in result['panels']] == ['photo', 'source', 'camera']
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
    from looktool.references import Cube
    document, _, _ = compiled_look(tmp_path)
    original = write_photo(tmp_path / 'shot.png')
    result = lookpreview.render(document, tmp_path / 'shot.png', tmp_path / 'preview.png', model=model, grid_size=4)
    grid = Cube.from_values(lookpreview.prediction_grid(document, size=4, model=model))
    expected = lookpreview.to_bytes(grid.sample(original.reshape(-1, 3) / 255), original.shape)
    assert np.array_equal(result['panels'][-1]['pixels'], expected)
