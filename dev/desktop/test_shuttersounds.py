"""Bundled shutter sounds: catalog, licences and the build-time preparation; no camera access."""
import json
from pathlib import Path
import sys
import wave

import pytest

from desktopapp import shuttersounds

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'dev/desktop'))
import prepare_shutter_sounds


def write_wav(path, seconds=0.5, rate=48000, channels=1):
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), 'wb') as clip:
        clip.setnchannels(channels)
        clip.setsampwidth(2)
        clip.setframerate(rate)
        clip.writeframes(b'\x00\x01' * channels * int(round(seconds * rate)))
    return path


def entry(**changes):
    value = {'id': 'leica-m3', 'name': 'Leica M3', 'file': 'leica-m3.wav',
             'source': {'title': 'Leica M3 Shutter sound', 'author': 'petrich0r',
                        'url': 'https://freesound.org/s/683763/', 'licence': 'CC BY 4.0'},
             'changes': 'Trimmed to one release, mixed to mono.',
             'credit': 'Leica M3 Shutter sound by petrich0r -- https://freesound.org/s/683763/ -- License: '
                       'Attribution 4.0 (https://creativecommons.org/licenses/by/4.0/). '
                       'Changes: Trimmed to one release, mixed to mono.'}
    value.update(changes)
    return value


def write_catalog(folder, entries, *, wav=True):
    folder.mkdir(parents=True, exist_ok=True)
    (folder / 'catalog.json').write_text(json.dumps({'schema': shuttersounds.SCHEMA, 'sounds': entries}))
    if wav:
        for item in entries:
            if isinstance(item, dict) and isinstance(item.get('file'), str) and '/' not in item['file']:
                write_wav(folder / item['file'])
    return folder


def test_catalog_lists_sounds_in_rank_order_with_their_length_and_credit(tmp_path):
    second = entry(id='hasselblad-500c', name='Hasselblad 500C', file='hasselblad-500c.wav', changes='',
                   source={'title': 'Hassselblad C500 shutter.wav', 'author': 'Tonik1105',
                           'url': 'https://freesound.org/s/520683/', 'licence': 'CC0 1.0'},
                   credit='Hassselblad C500 shutter.wav by Tonik1105 -- https://freesound.org/s/520683/ -- '
                          'License: Creative Commons 0')
    folder = write_catalog(tmp_path / 'sounds', [entry(), second], wav=False)
    write_wav(folder / 'leica-m3.wav', seconds=0.55)
    write_wav(folder / 'hasselblad-500c.wav', seconds=0.68, rate=44100, channels=2)
    first, then = shuttersounds.catalog(folder)
    assert [first['name'], then['name']] == ['Leica M3', 'Hasselblad 500C']
    assert first['path'] == folder / 'leica-m3.wav' and first['seconds'] == 0.55 and then['seconds'] == 0.68
    assert 'petrich0r' in first['credit'] and first['source']['licence'] == 'CC BY 4.0'


def test_a_missing_library_is_empty(tmp_path):
    assert shuttersounds.catalog(tmp_path / 'absent') == []


@pytest.mark.parametrize('broken', [
    dict(file='../leica-m3.wav'),
    dict(file='sub/leica-m3.wav'),
    dict(file='leica-m3.mp3'),
    dict(name=''),
    dict(id='Leica M3'),
    dict(credit=''),
    dict(source={'title': 't', 'author': 'a', 'url': 'http://freesound.org/s/1/', 'licence': 'CC BY 4.0'}),
    dict(source={'title': 't', 'author': 'a', 'url': 'https://freesound.org/s/1/', 'licence': 'CC BY-NC 4.0'}),
    dict(source={'title': 't', 'author': 'a', 'url': 'https://freesound.org/s/1/'}),
    dict(changes=''),            # CC BY needs the changes stated
    dict(changes=None),
])
def test_catalog_rejects_entries_that_break_the_licence_or_leave_the_folder(tmp_path, broken):
    folder = write_catalog(tmp_path / 'sounds', [entry(**broken)])
    with pytest.raises(ValueError):
        shuttersounds.catalog(folder)


def test_catalog_rejects_incomplete_entries_unknown_schema_and_duplicates(tmp_path):
    incomplete = entry(); del incomplete['credit']
    for entries in ([incomplete], ['leica-m3'], [entry(), entry()]):
        with pytest.raises(ValueError):
            shuttersounds.catalog(write_catalog(tmp_path / ('s%d' % len(str(entries))), entries))
    folder = tmp_path / 'other'; folder.mkdir()
    (folder / 'catalog.json').write_text(json.dumps({'schema': 'other/1', 'sounds': []}))
    with pytest.raises(ValueError):
        shuttersounds.catalog(folder)


def test_catalog_rejects_a_missing_sound_file(tmp_path):
    folder = write_catalog(tmp_path / 'sounds', [entry()], wav=False)
    with pytest.raises(FileNotFoundError):
        shuttersounds.catalog(folder)


@pytest.mark.parametrize('seconds', [0.005, 2.5])
def test_catalog_rejects_clips_outside_the_cameras_length_limits(tmp_path, seconds):
    folder = write_catalog(tmp_path / 'sounds', [entry()], wav=False)
    write_wav(folder / 'leica-m3.wav', seconds=seconds)
    with pytest.raises(ValueError, match='length'):
        shuttersounds.catalog(folder)


def test_catalog_rejects_a_file_that_is_not_a_pcm_wav(tmp_path):
    folder = write_catalog(tmp_path / 'sounds', [entry()], wav=False)
    (folder / 'leica-m3.wav').write_bytes(b'ID3 not a wav')
    with pytest.raises(ValueError):
        shuttersounds.catalog(folder)


def sources(folder, sounds):
    folder.mkdir(parents=True, exist_ok=True)
    (folder / 'sources.json').write_text(json.dumps({'schema': prepare_shutter_sounds.SOURCES, 'sounds': sounds}))
    return folder


def source(**changes):
    value = {'id': 'leica-m3', 'name': 'Leica M3', 'file': '1_leica-m3_CC-BY-4.0.wav',
             'title': 'Leica M3 Shutter sound', 'author': 'petrich0r', 'url': 'https://freesound.org/s/683763/',
             'licence': 'CC BY 4.0', 'changes': 'Trimmed to one release, mixed to mono.'}
    value.update(changes)
    return value


def cc0(**changes):
    return source(id='hasselblad-500c', name='Hasselblad 500C', file='2_hasselblad-500c_CC0.wav',
                  title='Hassselblad C500 shutter.wav', author='Tonik1105', url='https://freesound.org/s/520683/',
                  licence='CC0 1.0', changes='Trimmed to one release.', **changes)


def test_prepare_copies_the_clips_and_writes_the_catalog_and_credits(tmp_path):
    folder = sources(tmp_path / 'curated', [source(), cc0()])
    write_wav(folder / '1_leica-m3_CC-BY-4.0.wav', seconds=0.55)
    write_wav(folder / '2_hasselblad-500c_CC0.wav', seconds=0.68)
    target = tmp_path / 'desktop-assets/shutter-sounds-v1'
    prepare_shutter_sounds.prepare(folder, target)
    assert sorted(p.name for p in target.iterdir()) == ['CREDITS.txt', 'catalog.json', 'hasselblad-500c.wav', 'leica-m3.wav']
    leica, hasselblad = shuttersounds.catalog(target)
    assert leica['credit'] == ('Leica M3 Shutter sound by petrich0r -- https://freesound.org/s/683763/ -- License: '
                               'Attribution 4.0 (https://creativecommons.org/licenses/by/4.0/). '
                               'Changes: Trimmed to one release, mixed to mono.')
    assert hasselblad['credit'] == ('Hassselblad C500 shutter.wav by Tonik1105 -- https://freesound.org/s/520683/ -- '
                                    'License: Creative Commons 0. Changes: Trimmed to one release.')
    credits = (target / 'CREDITS.txt').read_text(encoding='utf-8')
    assert leica['credit'] in credits and hasselblad['credit'] in credits
    assert 'not covered by' in credits  # the code licence does not cover the recordings
    prepare_shutter_sounds.prepare(folder, target)  # rerunning replaces the library cleanly
    assert len(shuttersounds.catalog(target)) == 2


@pytest.mark.parametrize('broken', [dict(id='../x'), dict(file='../outside.wav'), dict(licence='CC BY-NC 4.0')])
def test_prepare_rejects_unsafe_or_unlicensed_sources_and_keeps_the_old_library(tmp_path, broken):
    good = sources(tmp_path / 'good', [source()])
    write_wav(good / '1_leica-m3_CC-BY-4.0.wav')
    target = tmp_path / 'desktop-assets/shutter-sounds-v1'
    prepare_shutter_sounds.prepare(good, target)
    bad = sources(tmp_path / 'bad', [source(**broken)])
    write_wav(bad / '1_leica-m3_CC-BY-4.0.wav')
    write_wav(tmp_path / 'outside.wav')
    with pytest.raises(ValueError):
        prepare_shutter_sounds.prepare(bad, target)
    assert [sound['id'] for sound in shuttersounds.catalog(target)] == ['leica-m3']


def test_prepare_refuses_to_replace_a_folder_that_is_not_a_sound_library(tmp_path):
    folder = sources(tmp_path / 'curated', [source()])
    write_wav(folder / '1_leica-m3_CC-BY-4.0.wav')
    target = tmp_path / 'desktop-assets/shutter-sounds-v1'
    target.mkdir(parents=True)
    (target / 'precious.txt').write_text('keep me')
    with pytest.raises(RuntimeError):
        prepare_shutter_sounds.prepare(folder, target)
    assert (target / 'precious.txt').read_text() == 'keep me'


def test_a_wav_header_with_no_sample_rate_is_rejected(tmp_path):
    folder = write_catalog(tmp_path / 'sounds', [entry()], wav=False)
    path = write_wav(folder / 'leica-m3.wav')
    data = bytearray(path.read_bytes())
    data[24:28] = (0).to_bytes(4, 'little')  # the fmt chunk's sample rate
    path.write_bytes(bytes(data))
    with pytest.raises(ValueError):
        shuttersounds.catalog(folder)
