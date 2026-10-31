"""Render the README's figures, each as a light and a dark image so GitHub shows the one that matches the
reader's theme:

- looks-{light,dark}.jpg: a sample photo, then the same photo through five of the app's open film looks,
  as the camera renders each in a Custom slot (lookpreview's prediction, the app's own "Preview on my
  photos"). The photo is a camera JPEG shot in Standard; no exposure compensation is added.
- convert-{light,dark}.png and convert-zh-{light,dark}.png: the converter (Make an A7Look) with an example
  LUT filled in, in English and in Chinese.

    venv/bin/python dev/desktop/readme_figures.py PHOTO --crop 0.05,0,0.89,0.84 --out docs/images/readme

The looks come from desktop-assets/film-looks-v1, the open spektrafilm set (Andrea Volpato, CC BY-SA 4.0),
never from the personal library.
"""
import argparse
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
for folder in (ROOT / 'src', ROOT / 'src/looks'):
    if str(folder) not in sys.path:
        sys.path.insert(0, str(folder))

LIBRARY = ROOT / 'desktop-assets/film-looks-v1'
LOOKS = ('portra400', 'kodachrome64', 'velvia100', 'gold200', 'vision3-500t-2383')
# GitHub's own page colours, so each figure sits on the reader's background.
THEMES = {'light': dict(ground='#ffffff', name='#1f2328', note='#59636e'),
          'dark': dict(ground='#0d1117', name='#f0f6fc', note='#9198a1')}
TILE, GAP, MARGIN, LABEL = 600, 24, 24, 64
FONT = '/System/Library/Fonts/Helvetica.ttc'


def library():
    """{id: catalog row} of the open film looks."""
    catalog = json.loads((LIBRARY / 'catalog.json').read_text(encoding='utf-8'))
    rows = catalog['looks'] if isinstance(catalog, dict) else catalog
    found = {row['id']: row for row in rows}
    for row in found.values():
        if row['source']['project'] != 'spektrafilm':
            raise ValueError('%s is not an open spektrafilm look' % row['id'])
    return found


def tiles(photo, ids=LOOKS, crop=None):
    """[(name, note, PIL image)]: the photo in sRGB at TILE wide, then each look's predicted camera result.
    `crop` is (left, top, right, bottom) as fractions of the photo, applied first."""
    import numpy as np
    from PIL import Image, ImageOps
    from looktool import lookpreview
    from looktool.references import Cube
    original = Image.open(photo)
    image, _ = lookpreview.srgb_photo(ImageOps.exif_transpose(original), original)
    if crop:
        left, top, right, bottom = crop
        image = image.crop((round(left * image.width), round(top * image.height),
                            round(right * image.width), round(bottom * image.height)))
    image = image.resize((TILE, round(image.height * TILE / image.width)), Image.LANCZOS)
    pixels = np.asarray(image)
    flat = pixels.reshape(-1, 3) / 255
    looks = library()
    result = [('Original', 'camera JPEG, Standard', image)]
    for look_id in ids:
        row = looks[look_id]
        document = json.loads((LIBRARY / row['file']).read_text(encoding='utf-8'))
        camera = Cube.from_values(lookpreview.prediction_grid(document))
        result.append((row['name'], row['kind'], Image.fromarray(lookpreview.to_bytes(camera.sample(flat), pixels.shape))))
    return result


def sheet(rows, theme, columns=3):
    """The tiles in a grid on the theme's ground, each named under it."""
    from PIL import Image, ImageDraw, ImageFont
    colours = THEMES[theme]
    height = rows[0][2].height
    lines = (len(rows) + columns - 1) // columns
    canvas = Image.new('RGB', (2 * MARGIN + columns * TILE + (columns - 1) * GAP,
                               2 * MARGIN + lines * (height + LABEL) + (lines - 1) * GAP), colours['ground'])
    draw = ImageDraw.Draw(canvas)
    name_font, note_font = ImageFont.truetype(FONT, 26), ImageFont.truetype(FONT, 22)
    for index, (name, note, image) in enumerate(rows):
        x = MARGIN + (index % columns) * (TILE + GAP)
        y = MARGIN + (index // columns) * (height + LABEL + GAP)
        canvas.paste(image, (x, y))
        draw.text((x, y + height + 14), name, fill=colours['name'], font=name_font)
        draw.text((x + draw.textlength(name, font=name_font) + 12, y + height + 18), note, fill=colours['note'], font=note_font)
    return canvas


def looks_figures(photo, out, crop=None):
    rows = tiles(photo, crop=crop)
    for theme in THEMES:
        sheet(rows, theme).save(out / ('looks-%s.jpg' % theme), quality=90, optimize=True, progressive=True)


def app_figures(out, scale=2):
    """The converter dialog (Make an A7Look) with an example LUT filled in, in English and in Chinese, light
    and dark, offscreen at `scale`. The app runs on a temporary settings folder, so this never touches yours."""
    import tempfile
    from unittest.mock import patch
    os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
    os.environ['QT_SCALE_FACTOR'] = str(scale)
    with tempfile.TemporaryDirectory(prefix='readme-figures-') as data:
        os.environ['A7C2_DESKTOP_DATA'] = data
        from PySide6 import QtWidgets as W
        from desktopapp import theme
        from desktopapp.paths import write_json
        from desktopapp.window import Window, configure_application
        app = W.QApplication.instance() or W.QApplication([])
        configure_application(app)
        for language, prefix in (('en', 'convert'), ('zh_CN', 'convert-zh')):
            write_json(Path(data) / 'desktop.json', dict(language=language, connection_notice_seen=True))
            for scheme in THEMES:
                app.setProperty('a7c2_theme', None)
                with patch.object(theme, 'mode', return_value=scheme):
                    theme.apply(app)
                    window = Window()
                    window.show()

                    def grab(dialog, name='%s-%s.png' % (prefix, scheme)):
                        # Example names, and the response file as a repository path: no path from this computer.
                        for field, value in (('compile_source', 'My Film Look.cube'), ('compile_name', 'My Film Look'),
                                             ('compile_output', 'My Film Look.a7look'),
                                             ('compile_model', 'calibration/a7c2-2.01.virtual.npz')):
                            window.fields[field].setText(value)
                        dialog.show()
                        app.processEvents()
                        if app.focusWidget() is not None:
                            app.focusWidget().clearFocus()  # no text cursor in the picture
                        app.processEvents()
                        dialog.grab().toImage().save(str(out / name))
                        return 0
                    with patch.object(W.QDialog, 'exec', grab):
                        window.compiler_dialog()
                    window.close()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('photo', type=Path, help='a camera JPEG shot in Standard (ST)')
    parser.add_argument('--crop', help='left,top,right,bottom as fractions of the photo, e.g. 0.05,0,0.89,0.84')
    parser.add_argument('--out', type=Path, default=ROOT / 'docs/images/readme')
    args = parser.parse_args(argv)
    args.out.mkdir(parents=True, exist_ok=True)
    looks_figures(args.photo, args.out, tuple(float(v) for v in args.crop.split(',')) if args.crop else None)
    app_figures(args.out)
    for path in sorted(args.out.iterdir()):
        print(path, path.stat().st_size)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
