"""Identity HALD images and their conversion to .cube; offline, no editor or camera."""
import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest

import numpy as np
from PIL import ImageCms
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


class HaldTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.folder = Path(temporary.name)

    def test_identity_holds_the_lattice_twice_one_copy_below_the_other(self):
        image = hald.identity(LEVEL)
        self.assertEqual((image.shape, image.dtype), ((2 * LEVEL ** 3, LEVEL ** 3, 3), np.uint16))
        top, bottom = image[:LEVEL ** 3], image[LEVEL ** 3:]
        self.assertTrue(np.array_equal(top.reshape(-1, 3), np.round(lattice() * 65535).astype(np.uint16)))  # red fastest
        self.assertTrue(np.array_equal(bottom, top))  # not mirrored: a centred vignette must hit the copies differently

    def test_the_default_is_a_36_cube_in_a_216_pixel_block(self):
        self.assertEqual((hald.LEVEL, hald.identity().shape), (6, (432, 216, 3)))

    def test_identity_tiff_is_16_bit_rgb_with_an_srgb_profile(self):
        path = hald.write_identity(self.folder / 'hald.tif', LEVEL)
        with tifffile.TiffFile(path) as tiff:
            page = tiff.pages[0]
            self.assertEqual((page.dtype, page.shape, page.compression), (np.uint16, (2 * LEVEL ** 3, LEVEL ** 3, 3), 1))
            profile = ImageCms.ImageCmsProfile(io.BytesIO(page.tags['InterColorProfile'].value))
        self.assertIn('sRGB', ImageCms.getProfileDescription(profile))
        self.assertTrue(np.array_equal(hald.read(path), hald.identity(LEVEL) / 65535.0))

    def test_the_identity_converts_to_the_identity_cube(self):
        values = hald.to_cube(hald.identity(LEVEL) / 65535.0)
        self.assertEqual(values.shape, (N, N, N, 3))
        self.assertTrue(np.allclose(values.reshape(-1, 3), lattice(), atol=1 / 65535))

    def test_a_processed_hald_becomes_a_cube_of_that_look_that_parses_and_samples(self):
        tifffile.imwrite(self.folder / 'look.tif', processed(hald.identity(LEVEL)), photometric='rgb')
        report = hald.convert(self.folder / 'look.tif', self.folder / 'look.cube', title='Fixture "look"')
        cube = Cube(self.folder / 'look.cube')
        self.assertEqual(cube.values.shape, (N, N, N, 3))
        self.assertTrue(np.allclose(cube.sample(lattice()), look(lattice()), atol=1e-5))
        self.assertEqual((report['size'], report['copy_difference_max']), (N, 0))
        self.assertEqual((self.folder / 'look.cube').read_text().splitlines()[0], 'TITLE "Fixture look"')

    def test_an_8_bit_export_and_an_alpha_channel_are_accepted(self):
        image = np.round(processed(hald.identity(LEVEL)) / 257).astype(np.uint8)
        alpha = np.full(image.shape[:2] + (1,), 255, np.uint8)
        tifffile.imwrite(self.folder / 'look8.tif', np.concatenate([image, alpha], 2), photometric='rgb', extrasamples=[2])
        values = hald.to_cube(hald.read(self.folder / 'look8.tif'))
        self.assertTrue(np.allclose(values.reshape(-1, 3), look(lattice()), atol=1 / 255))

    def test_grain_is_detected_instead_of_baked_into_the_cube(self):
        image = processed(hald.identity(LEVEL)).astype(float)
        grain = np.random.default_rng(3).normal(0, 3 * 257, image.shape)  # about three 8-bit levels
        with self.assertRaisesRegex(ValueError, 'grain'):
            hald.to_cube(np.clip(image + grain, 0, 65535) / 65535)

    def test_vignetting_is_detected_instead_of_baked_into_the_cube(self):
        image = processed(hald.identity(LEVEL)) / 65535.0
        height, width = image.shape[:2]
        y, x = np.mgrid[0:height, 0:width]
        falloff = 1 - .15 * (((x - width / 2) / width) ** 2 + ((y - height / 2) / height) ** 2)
        with self.assertRaisesRegex(ValueError, 'vignett'):
            hald.to_cube(image * falloff[..., None])

    def test_a_resized_cropped_or_non_rgb_image_is_rejected(self):
        for shape in ((54, 26, 3), (27, 27, 3), (64, 32, 3), (54, 27, 2)):
            with self.subTest(shape=shape), self.assertRaisesRegex(ValueError, 'resized|cropped|RGB'):
                hald.to_cube(np.zeros(shape))

    def test_an_unreadable_file_names_the_export_settings(self):
        path = self.folder / 'broken.tif'
        path.write_bytes(b'not a tiff')
        with self.assertRaisesRegex(ValueError, 'uncompressed 16-bit TIFF'):
            hald.read(path)

    def test_check_measures_how_far_an_export_is_from_the_identity(self):
        clean = hald.check(hald.identity(LEVEL) / 65535.0)
        self.assertLess(clean['identity_error_max'], .01)  # 16-bit rounding only
        self.assertEqual((clean['copy_difference_max'], clean['size']), (0, N))
        shifted = hald.check(processed(hald.identity(LEVEL)) / 65535.0)
        self.assertGreater(shifted['identity_error_max'], 10)
        self.assertEqual(shifted['copy_difference_max'], 0)

    def test_the_command_line_writes_converts_and_checks(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.assertEqual(hald.main(['identity', str(self.folder / 'id.tif'), '--level', str(LEVEL)]), 0)
            exported = processed(tifffile.imread(self.folder / 'id.tif'))
            tifffile.imwrite(self.folder / 'look.tif', exported, photometric='rgb')
            self.assertEqual(hald.main(['cube', str(self.folder / 'look.tif'), str(self.folder / 'look.cube')]), 0)
        self.assertEqual(Cube(self.folder / 'look.cube').values.shape, (N, N, N, 3))
        checked = io.StringIO()
        with contextlib.redirect_stdout(checked):
            self.assertEqual(hald.main(['check', str(self.folder / 'id.tif')]), 0)
        self.assertLess(json.loads(checked.getvalue())['identity_error_max'], .01)


if __name__ == '__main__':
    unittest.main()
