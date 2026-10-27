"""Identity HALD images for capturing an editor's colour look as a 3D .cube. No camera.

A HALD block of level L is an L^3 x L^3 image holding every colour of an
(L^2)^3 lattice, red varying fastest. Run the identity image through an editor
(for example DxO PhotoLab with a FilmPack rendering), export it unchanged in
size, and the exported pixels are the editor's colour transform at every
lattice point.

The image holds the block twice, one copy below the other. A pure colour
transform gives both copies the same values; grain, vignetting or any other
effect that depends on pixel position does not, so it is reported instead of
being baked into the LUT. A copy is not mirrored, because a centred vignette
would hit mirrored copies identically.
"""
import argparse
import json
from pathlib import Path
import re
import numpy as np

# Level 6 is a 36^3 lattice in a 216 x 216 block: the size class of the bundled
# 33^3 looks. The camera's native table cannot use finer detail, and a 64^3
# cube would make each .a7look (which embeds its source cube) about 10 MB.
LEVEL = 6
# Largest difference between the two copies, in 8-bit levels, that still counts
# as the same colour transform; it allows for dithering in an 8-bit export.
TOLERANCE = 2.0
# Largest difference from the identity, in 8-bit levels, for a test export with no
# look applied to count as unchanged (no automatic correction switched on).
CLEAN = 1.0


def lattice(level):
    """The (level^2)^3 colours of a HALD block, red varying fastest."""
    from .references import lattice as cube_lattice
    return cube_lattice(level ** 2)


def identity(level=LEVEL):
    """The identity image as 16-bit RGB: two copies of the HALD block, one below the other."""
    side = level ** 3
    block = np.round(lattice(level) * 65535).astype(np.uint16).reshape(side, side, 3)
    return np.vstack([block, block])


def srgb_profile():
    from PIL import ImageCms
    return ImageCms.ImageCmsProfile(ImageCms.createProfile('sRGB')).tobytes()


def write_identity(path, level=LEVEL):
    """An uncompressed 16-bit sRGB TIFF of the identity image."""
    import tifffile
    tifffile.imwrite(path, identity(level), photometric='rgb', compression=None, iccprofile=srgb_profile())
    return Path(path)


def read(path):
    """An exported HALD as floats in 0..1, shape (height, width, 3).

    Refuses, from the header and before converting any pixels: a colour model other than
    RGB, an embedded profile other than sRGB (the cube would bake in a colour-space
    conversion), and a size this tool's identity image cannot have.
    """
    import tifffile
    name = Path(path).name
    try:
        with tifffile.TiffFile(path) as tiff:
            page = tiff.pages[0]
            if page.photometric != tifffile.PHOTOMETRIC.RGB:
                raise ValueError('%s is a %s image, not RGB; export the HALD as an uncompressed 16-bit RGB TIFF.'
                                 % (name, page.photometric.name))
            profile = page.tags.get('InterColorProfile')
            if profile is not None:
                described = profile_name(profile.value)
                if 'srgb' not in described.lower():
                    raise ValueError('%s was exported in %s; export the HALD in sRGB so the cube holds only the look.'
                                     % (name, described))
            level_of(page.imagewidth, page.imagelength)
            image = page.asarray()
            if page.planarconfig == tifffile.PLANARCONFIG.SEPARATE:
                image = np.moveaxis(image, 0, -1)  # per-channel planes: channels first
    except ValueError:
        raise
    except Exception as exc:  # tifffile reports bad files and missing codecs with many exception types
        raise ValueError('Cannot read %s (%s). Export the HALD as an uncompressed 16-bit TIFF.' % (name, exc)) from exc
    if image.dtype == np.uint16:
        scale = 65535.0
    elif image.dtype == np.uint8:
        scale = 255.0
    else:
        raise ValueError('%s has %s pixels; export the HALD as an uncompressed 16-bit TIFF.' % (name, image.dtype))
    if image.ndim != 3 or image.shape[2] < 3:
        raise ValueError('%s is not an RGB image; export the HALD as an uncompressed 16-bit RGB TIFF.' % name)
    return image[..., :3] / scale


def profile_name(icc):
    import io
    from PIL import ImageCms
    try:
        return ImageCms.getProfileDescription(ImageCms.ImageCmsProfile(io.BytesIO(bytes(icc)))).strip()
    except (OSError, ImageCms.PyCMSError):
        return 'an unreadable colour profile'


def level_of(width, height):
    """The HALD level of an identity export of this size; ValueError for any other size."""
    level = round(width ** (1 / 3))
    if not 2 <= level <= 16 or level ** 3 != width or height != 2 * width:
        raise ValueError('This image is %d x %d pixels, not a HALD from this tool: it was resized or cropped, '
                         'or it is a different file. Export at 100%% size.' % (width, height))
    return level


def copies(image):
    """(top, bottom, level) after checking the image is an unresized, uncropped identity export."""
    image = np.asarray(image, float)
    if image.ndim != 3 or image.shape[2] != 3:
        raise ValueError('The HALD image must be RGB')
    height, width = image.shape[:2]
    level = level_of(width, height)
    return image[:width], image[width:], level


def measure(image):
    """(report, mean of the two copies, level): how far the copies differ from each other and
    from the identity, in 8-bit levels. Never refuses; see accept()."""
    top, bottom, level = copies(image)
    mean = (top + bottom) / 2
    copy = np.abs(top - bottom) * 255
    error = np.abs(mean.reshape(-1, 3) - lattice(level)) * 255
    report = dict(level=level, size=level ** 2, copy_difference_max=float(copy.max()),
                  copy_difference_p99=float(np.percentile(copy, 99)), identity_error_max=float(error.max()),
                  identity_error_p99=float(np.percentile(error, 99)))
    return report, mean, level


def check(image):
    """measure()'s report alone (the command line's check, which reports and never refuses)."""
    return measure(image)[0]


def accept(image):
    """(cube values[b, g, r], report) for an exported HALD; refuses position-dependent effects."""
    report, mean, level = measure(image)
    if report['copy_difference_max'] > TOLERANCE:
        raise ValueError('The two copies of the HALD differ by up to %.1f levels, so the export has grain, '
                         'vignetting or another effect that depends on pixel position. A LUT cannot hold that: '
                         'switch it off and export again.' % report['copy_difference_max'])
    size = level ** 2
    return mean.reshape(size, size, size, 3), report


def to_cube(image):
    return accept(image)[0]


def write_cube(path, values, title):
    """A standalone 3D .cube, red varying fastest."""
    title = re.sub(r'["\\\x00-\x1f\x7f]', '', title).strip() or 'HALD capture'
    rows = ['TITLE "%s"' % title, '# Captured from an identity HALD image by A7C II Tools',
            'LUT_3D_SIZE %d' % len(values)]
    rows += ['%.6f %.6f %.6f' % tuple(row) for row in np.clip(values, 0, 1).reshape(-1, 3)]
    Path(path).write_text('\n'.join(rows) + '\n', encoding='utf-8')
    return Path(path)


def convert(source, output, title=None):
    """Exported HALD TIFF to .cube; returns the check report."""
    values, report = accept(read(source))
    write_cube(output, values, title or Path(source).stem)
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(prog='python -m looktool.hald', description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest='command', required=True)
    make = commands.add_parser('identity', help='write the identity HALD TIFF')
    make.add_argument('output'); make.add_argument('--level', type=int, default=LEVEL)
    cube = commands.add_parser('cube', help='convert an exported HALD TIFF to .cube')
    cube.add_argument('source'); cube.add_argument('output'); cube.add_argument('--title')
    inspect = commands.add_parser('check', help='measure an exported HALD against the identity')
    inspect.add_argument('source')
    args = parser.parse_args(argv)
    if args.command == 'identity':
        print(write_identity(args.output, args.level))
    elif args.command == 'cube':
        print(json.dumps(convert(args.source, args.output, args.title), indent=2))
    else:
        print(json.dumps(check(read(args.source)), indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
