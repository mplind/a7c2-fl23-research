"""Identity HALD images and their conversion to .cube; offline, no editor or camera."""
import io
import json
import numpy as np
from PIL import ImageCms
import pytest
import tifffile
from looktool import hald
from looktool.references import Cube

LEVEL = 3  # 9^3 lattice in a 27 x 27 block: small and fast, same layout as the default
N = LEVEL ** 2


def lattice(size=N):
    axis = np.linspace(0, 1, size)
    blue, green, red = np.meshgrid(axis, axis, axis, indexing='ij')
    return np.stack([red.ravel(), green.ravel(), blue.ravel()], 1)


def look(rgb):
    """A smooth, channel-mixing colour transform standing in for an editor's look."""
    mixed = rgb @ np.array([[.9, .05, .05], [.1, .8, .1], [0, .15, .85]]).T
    return np.clip(mixed, 0, 1) ** 1.2


def processed(image, function=look):
    """What an editor exports: the function applied to every pixel, as 16-bit."""
    values = function(image.reshape(-1, 3) / 65535.0)
    return np.round(np.clip(values, 0, 1) * 65535).astype(np.uint16).reshape(image.shape)


def test_identity_holds_the_lattice_twice_one_copy_below_the_other():
    image = hald.identity(LEVEL)
    assert image.shape == (2 * LEVEL ** 3, LEVEL ** 3, 3) and image.dtype == np.uint16
    top, bottom = image[:LEVEL ** 3], image[LEVEL ** 3:]
    assert np.array_equal(top.reshape(-1, 3), np.round(lattice() * 65535).astype(np.uint16))  # red varies fastest
    assert np.array_equal(bottom, top)  # not mirrored: a centred vignette must hit the copies differently


def test_the_default_is_a_36_cube_in_a_216_pixel_block():
    assert hald.LEVEL == 6 and hald.identity().shape == (432, 216, 3)


def test_identity_tiff_is_16_bit_rgb_with_an_srgb_profile(tmp_path):
    path = hald.write_identity(tmp_path / 'hald.tif', LEVEL)
    with tifffile.TiffFile(path) as tiff:
        page = tiff.pages[0]
        assert page.dtype == np.uint16 and page.shape == (2 * LEVEL ** 3, LEVEL ** 3, 3)
        assert page.compression == 1
        profile = ImageCms.ImageCmsProfile(io.BytesIO(page.tags['InterColorProfile'].value))
    assert 'sRGB' in ImageCms.getProfileDescription(profile)
    assert np.array_equal(hald.read(path), hald.identity(LEVEL) / 65535.0)


def test_the_identity_converts_to_the_identity_cube():
    values = hald.to_cube(hald.identity(LEVEL) / 65535.0)
    assert values.shape == (N, N, N, 3)
    assert np.allclose(values.reshape(-1, 3), lattice(), atol=1 / 65535)


def test_a_processed_hald_becomes_a_cube_of_that_look_that_parses_and_samples(tmp_path):
    image = processed(hald.identity(LEVEL))
    tifffile.imwrite(tmp_path / 'look.tif', image, photometric='rgb')
    report = hald.convert(tmp_path / 'look.tif', tmp_path / 'look.cube', title='Fixture "look"')
    cube = Cube(tmp_path / 'look.cube')
    assert cube.values.shape == (N, N, N, 3)
    assert np.allclose(cube.sample(lattice()), look(lattice()), atol=1e-5)
    assert report['size'] == N and report['copy_difference_max'] == 0
    assert (tmp_path / 'look.cube').read_text().splitlines()[0] == 'TITLE "Fixture look"'


def test_an_8_bit_export_and_an_alpha_channel_are_accepted(tmp_path):
    image = np.round(processed(hald.identity(LEVEL)) / 257).astype(np.uint8)
    alpha = np.full(image.shape[:2] + (1,), 255, np.uint8)
    tifffile.imwrite(tmp_path / 'look8.tif', np.concatenate([image, alpha], 2), photometric='rgb', extrasamples=[2])
    values = hald.to_cube(hald.read(tmp_path / 'look8.tif'))
    assert np.allclose(values.reshape(-1, 3), look(lattice()), atol=1 / 255)


def test_grain_is_detected_instead_of_baked_into_the_cube():
    image = processed(hald.identity(LEVEL)).astype(float)
    grain = np.random.default_rng(3).normal(0, 3 * 257, image.shape)  # about three 8-bit levels
    with pytest.raises(ValueError, match='grain'):
        hald.to_cube(np.clip(image + grain, 0, 65535) / 65535)


def test_vignetting_is_detected_instead_of_baked_into_the_cube():
    image = processed(hald.identity(LEVEL)) / 65535.0
    height, width = image.shape[:2]
    y, x = np.mgrid[0:height, 0:width]
    falloff = 1 - .15 * (((x - width / 2) / width) ** 2 + ((y - height / 2) / height) ** 2)
    with pytest.raises(ValueError, match='vignett'):
        hald.to_cube(image * falloff[..., None])


@pytest.mark.parametrize('shape', [(54, 26, 3), (27, 27, 3), (64, 32, 3), (54, 27, 2)])
def test_a_resized_cropped_or_non_rgb_image_is_rejected(shape):
    with pytest.raises(ValueError, match='resized|cropped|RGB'):
        hald.to_cube(np.zeros(shape))


def test_an_unreadable_file_names_the_export_settings(tmp_path):
    path = tmp_path / 'broken.tif'; path.write_bytes(b'not a tiff')
    with pytest.raises(ValueError, match='uncompressed 16-bit TIFF'):
        hald.read(path)


def test_check_measures_how_far_an_export_is_from_the_identity():
    clean = hald.check(hald.identity(LEVEL) / 65535.0)
    assert clean['identity_error_max'] < .01 and clean['copy_difference_max'] == 0 and clean['size'] == N  # 16-bit rounding
    shifted = hald.check(processed(hald.identity(LEVEL)) / 65535.0)
    assert shifted['identity_error_max'] > 10 and shifted['copy_difference_max'] == 0


def test_the_command_line_writes_converts_and_checks(tmp_path, capsys):
    assert hald.main(['identity', str(tmp_path / 'id.tif'), '--level', str(LEVEL)]) == 0
    tifffile.imwrite(tmp_path / 'look.tif', processed(tifffile.imread(tmp_path / 'id.tif')), photometric='rgb')
    assert hald.main(['cube', str(tmp_path / 'look.tif'), str(tmp_path / 'look.cube')]) == 0
    assert Cube(tmp_path / 'look.cube').values.shape == (N, N, N, 3)
    capsys.readouterr()
    assert hald.main(['check', str(tmp_path / 'id.tif')]) == 0
    assert json.loads(capsys.readouterr().out)['identity_error_max'] < .01
