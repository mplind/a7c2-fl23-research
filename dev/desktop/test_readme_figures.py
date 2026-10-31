"""readme_figures: the README's look sheet uses only the open spektrafilm looks, and lays its tiles out on
each theme's page colour. The converter screenshots need a display and are checked by eye when regenerated."""
import json

import pytest
from PIL import Image

import readme_figures


def catalog(folder, *rows):
    folder.mkdir(parents=True, exist_ok=True)
    (folder / 'catalog.json').write_text(json.dumps(dict(schema='a7c2-film-look-library/1', looks=list(rows))),
                                         encoding='utf-8')


def row(look_id, project):
    return dict(id=look_id, name=look_id, kind='negative', file=look_id + '.a7look', source=dict(project=project))


def test_the_library_lists_the_open_looks_by_id(tmp_path, monkeypatch):
    catalog(tmp_path, row('portra400', 'spektrafilm'), row('gold200', 'spektrafilm'))
    monkeypatch.setattr(readme_figures, 'LIBRARY', tmp_path)
    assert sorted(readme_figures.library()) == ['gold200', 'portra400']


@pytest.mark.parametrize('project', ['dehancer', 'dxo-filmpack', 'personal'])
def test_a_look_from_any_other_project_stops_the_figures(tmp_path, monkeypatch, project):
    catalog(tmp_path, row('portra400', 'spektrafilm'), row('dh-portra400', project))
    monkeypatch.setattr(readme_figures, 'LIBRARY', tmp_path)
    with pytest.raises(ValueError, match='dh-portra400 is not an open spektrafilm look'):
        readme_figures.library()


def test_the_figures_read_the_public_library_never_the_personal_one():
    assert readme_figures.LIBRARY == readme_figures.ROOT / 'desktop-assets/film-looks-v1'
    assert 'personal' not in readme_figures.LIBRARY.parts


@pytest.mark.parametrize('theme', ['light', 'dark'])
def test_the_sheet_is_three_columns_on_the_theme_page_colour(theme):
    tile = Image.new('RGB', (readme_figures.TILE, 400), '#808080')
    rows = [('Look %d' % i, 'negative', tile) for i in range(6)]
    sheet = readme_figures.sheet(rows, theme)
    t = readme_figures
    assert sheet.size == (2 * t.MARGIN + 3 * t.TILE + 2 * t.GAP, 2 * t.MARGIN + 2 * (400 + t.LABEL) + t.GAP)
    ground = Image.new('RGB', (1, 1), t.THEMES[theme]['ground']).getpixel((0, 0))
    assert sheet.getpixel((0, 0)) == ground
    assert sheet.getpixel((t.MARGIN + 5, t.MARGIN + 5)) == (128, 128, 128)  # the first tile


@pytest.mark.skipif(not (readme_figures.LIBRARY / 'catalog.json').is_file(),
                    reason='the public film-look library is not in this checkout')
def test_the_sheet_photo_is_cropped_then_shown_through_each_chosen_look(tmp_path):
    photo = tmp_path / 'photo.jpg'
    Image.new('RGB', (1000, 500), (150, 120, 90)).save(photo, quality=95)
    assert set(readme_figures.LOOKS) <= set(readme_figures.library())
    tiles = readme_figures.tiles(photo, ids=readme_figures.LOOKS[:1], crop=(0, 0, 0.5, 1))  # one look keeps it quick
    assert [name for name, _, _ in tiles] == ['Original', readme_figures.library()[readme_figures.LOOKS[0]]['name']]
    for _, _, image in tiles:
        assert image.size == (readme_figures.TILE, readme_figures.TILE)  # a 500x500 crop, scaled to TILE wide
    assert tiles[1][2].getpixel((10, 10)) != tiles[0][2].getpixel((10, 10))  # the look changed the colour
