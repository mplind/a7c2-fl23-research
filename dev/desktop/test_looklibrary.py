"""Film look library, fit ratings and the build-time library preparation; no camera access."""
import json
from pathlib import Path
import sys
import pytest
from desktopapp import looklibrary

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'dev/desktop'))
import prepare_film_looks
from looksamples import look_file


@pytest.mark.parametrize('mae,p95,rating', [
    (2.39, 8.02, 'good'),      # the bundled library's median look
    (2.40, 8.00, 'fair'),
    (2.00, 8.03, 'fair'),
    (4.82, 14.76, 'fair'),     # the worst accepted bundled look (Classic Negative)
    (4.83, 10.00, 'poor'),
    (3.00, 14.77, 'poor'),
])
def test_fit_rating_is_measured_against_the_bundled_library(tmp_path, mae, p95, rating):
    result = looklibrary.file_fit(look_file(tmp_path / 'look.a7look', mae=mae, p95=p95))
    assert (result['rating'], result['mae'], result['p95']) == (rating, mae, p95)


def test_a_look_without_held_out_metrics_has_an_unknown_fit(tmp_path):
    assert looklibrary.file_fit(look_file(tmp_path / 'look.a7look'))['rating'] == 'unknown'


def test_an_unreadable_file_is_reported_as_invalid(tmp_path):
    path = tmp_path / 'broken.a7look'; path.write_text('{"schema": "other"}')
    result = looklibrary.file_fit(path)
    assert result['rating'] == 'invalid' and result['error']


def entry(file='portra400.a7look', **changes):
    value = {'id': 'portra400', 'name': 'Portra 400', 'kind': 'negative', 'file': file,
             'source': {'project': 'spektrafilm', 'author': 'Andrea Volpato',
                        'url': 'https://github.com/andreavolpato/spektrafilm', 'licence': 'CC BY-SA 4.0'},
             'modification': 'Baked to a 33^3 sRGB LUT and fitted to the A7C II table', 'shareable': True, 'notes': ''}
    value.update(changes)
    return value


def write_catalog(folder, entries):
    folder.mkdir(parents=True, exist_ok=True)
    (folder / 'catalog.json').write_text(json.dumps({'schema': looklibrary.SCHEMA, 'looks': entries}))
    return folder


def test_catalog_lists_each_look_with_its_source_licence_and_measured_fit(tmp_path):
    folder = write_catalog(tmp_path / 'library', [entry()])
    look_file(folder / 'portra400.a7look', mae=3.07, p95=9.38, name='Portra 400')
    [look] = looklibrary.catalog(folder)
    assert look['name'] == 'Portra 400' and look['path'] == folder / 'portra400.a7look'
    assert look['source']['licence'] == 'CC BY-SA 4.0'
    assert look['fit']['rating'] == 'fair'


@pytest.mark.parametrize('broken', [
    entry(source={'project': 'spektrafilm', 'author': 'Andrea Volpato', 'url': 'https://example.org'}),
    entry(file='../outside.a7look'),
    entry(kind='mystery'),
])
def test_catalog_rejects_entries_without_licence_inside_path_or_known_kind(tmp_path, broken):
    folder = write_catalog(tmp_path / 'library', [broken])
    look_file(folder / 'portra400.a7look', mae=3.0, p95=9.0)
    with pytest.raises(ValueError):
        looklibrary.catalog(folder)


def test_catalog_rejects_a_missing_look_file(tmp_path):
    with pytest.raises(FileNotFoundError):
        looklibrary.catalog(write_catalog(tmp_path / 'library', [entry()]))


def test_a_missing_library_is_empty(tmp_path):
    assert looklibrary.catalog(tmp_path / 'absent') == []


def test_prepare_copies_kept_looks_licences_and_builds_the_catalog(tmp_path):
    source = tmp_path / 'looks'; source.mkdir()
    for slug in ('portra400', 'rejected'):
        look_file(source / (slug + '.a7look'), mae=3.0, p95=9.0, name=slug)
    for name in prepare_film_looks.NOTICES:
        (source / name).write_text('notice ' + name)
    metrics = {'looks': [
        {'slug': 'portra400', 'camera_name': 'Portra 400', 'kind': 'negative', 'kept': True,
         'source': {'project': 'spektrafilm', 'author': 'Andrea Volpato',
                    'url': 'https://github.com/andreavolpato/spektrafilm', 'licence': 'CC BY-SA 4.0 (profiles and LUTs); code GPL-3.0'}},
        {'slug': 'rejected', 'camera_name': 'Rejected', 'kind': 'negative', 'kept': False,
         'source': {'project': 'x', 'author': 'y', 'url': 'https://example.org', 'licence': 'MIT'}}]}
    (source / 'metrics.json').write_text(json.dumps(metrics))
    target = tmp_path / 'desktop-assets/film-looks-v1'
    prepare_film_looks.prepare(source, target)
    assert sorted(p.name for p in target.iterdir()) == sorted(['catalog.json', 'portra400.a7look', *prepare_film_looks.NOTICES])
    [look] = looklibrary.catalog(target)
    assert (look['name'], look['source']['licence'], look['shareable']) == (
        'Portra 400', 'CC BY-SA 4.0 (profiles and LUTs); code GPL-3.0', True)
    prepare_film_looks.prepare(source, target)  # rerunning replaces the library cleanly
    assert len(looklibrary.catalog(target)) == 1


def test_catalog_rejects_duplicate_ids(tmp_path):
    folder = write_catalog(tmp_path / 'library', [entry(), entry()])
    look_file(folder / 'portra400.a7look', mae=3.0, p95=9.0)
    with pytest.raises(ValueError, match='Duplicate'):
        looklibrary.catalog(folder)


def test_catalog_rejects_a_plain_http_source(tmp_path):
    source = dict(entry()['source'], url='http://example.org')
    folder = write_catalog(tmp_path / 'library', [entry(source=source)])
    look_file(folder / 'portra400.a7look', mae=3.0, p95=9.0)
    with pytest.raises(ValueError, match='https'):
        looklibrary.catalog(folder)


def prepared_source(tmp_path, looks):
    source = tmp_path / 'looks'; source.mkdir()
    for look in looks:
        if look['kept'] and prepare_film_looks.SLUG.match(look['slug']):
            look_file(source / (look['slug'] + '.a7look'), mae=3.0, p95=9.0)
    for name in prepare_film_looks.NOTICES:
        (source / name).write_text(name)
    (source / 'metrics.json').write_text(json.dumps({'looks': looks}))
    return source


def kept(slug, licence='CC BY-SA 4.0', **extra):
    return dict({'slug': slug, 'camera_name': slug.title(), 'kind': 'slide', 'kept': True,
                 'source': {'project': 'p', 'author': 'a', 'url': 'https://example.org', 'licence': licence}}, **extra)


def test_prepare_marks_only_open_licences_shareable_and_records_caveats(tmp_path):
    source = prepared_source(tmp_path, [kept('velvia100', steep_curve=True), kept('private', licence='Personal use only')])
    entries = {e['id']: e for e in prepare_film_looks.prepare(source, tmp_path / 'film-looks-v1')}
    assert entries['velvia100']['shareable'] and not entries['private']['shareable']
    assert prepare_film_looks.STEEP in entries['velvia100']['notes']
    assert prepare_film_looks.CAVEATS['velvia100'] in entries['velvia100']['notes']
    assert entries['private']['notes'] == ''
    assert all(e['modification'][0].isupper() for e in entries.values())


def test_prepare_rejects_an_unsafe_slug_and_leaves_the_old_library(tmp_path):
    target = tmp_path / 'film-looks-v1'
    prepare_film_looks.prepare(prepared_source(tmp_path, [kept('portra400')]), target)
    other = tmp_path / 'other'; other.mkdir()
    (other / 'metrics.json').write_text(json.dumps({'looks': [kept('../escape')]}))
    with pytest.raises(ValueError, match='slug'):
        prepare_film_looks.prepare(other, target)
    assert [look['id'] for look in looklibrary.catalog(target)] == ['portra400']


def test_prepare_refuses_to_replace_a_folder_that_is_not_a_library(tmp_path):
    target = tmp_path / 'film-looks-v1'; target.mkdir()
    (target / 'keep.txt').write_text('mine')
    with pytest.raises(RuntimeError, match='not a film look library'):
        prepare_film_looks.prepare(prepared_source(tmp_path, [kept('portra400')]), target)
    assert (target / 'keep.txt').read_text() == 'mine'


def test_prepare_keeps_the_old_library_when_the_new_catalog_is_invalid(tmp_path):
    target = tmp_path / 'film-looks-v1'
    prepare_film_looks.prepare(prepared_source(tmp_path, [kept('portra400')]), target)
    broken = tmp_path / 'broken'; broken.mkdir()
    look_file(broken / 'mystery.a7look', mae=3.0, p95=9.0)
    for name in prepare_film_looks.NOTICES:
        (broken / name).write_text(name)
    (broken / 'metrics.json').write_text(json.dumps({'looks': [kept('mystery', kind='mystery')]}))
    with pytest.raises(ValueError, match='kind'):
        prepare_film_looks.prepare(broken, target)
    assert [look['id'] for look in looklibrary.catalog(target)] == ['portra400']


def test_fit_concerns_name_only_poor_unknown_and_unreadable_looks(tmp_path):
    good = look_file(tmp_path / 'good.a7look', mae=2.0, p95=7.0)
    fair = look_file(tmp_path / 'fair.a7look', mae=4.0, p95=12.0)
    poor = look_file(tmp_path / 'poor.a7look', mae=6.0, p95=20.0)
    unknown = look_file(tmp_path / 'unknown.a7look')
    concerns = looklibrary.fit_concerns([dict(slot=n, path=str(p)) for n, p in
                                         enumerate((good, fair, poor, unknown, tmp_path / 'missing.a7look'), 1)])
    assert [(c['slot'], c['fit']['rating']) for c in concerns] == [(3, 'poor'), (4, 'unknown'), (5, 'invalid')]
