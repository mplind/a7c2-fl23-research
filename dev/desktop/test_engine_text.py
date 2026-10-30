"""engine_text shows data as it is, finds a message by one lookup, and reads only the specifiers the
catalogues use. Offline; no window."""
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import textwrap

import pytest

from desktopapp import engine_text
from desktopapp.en import STRINGS
from desktopapp.en_engine import ENGINE
from desktopapp.engine_text import CJK, translate_line, translate_text
from looktool.buildprofile import BUILDS, JOB_OTHER_BUILD

ROOT = Path(__file__).resolve().parents[2]
FREESOUND = '“%(title)s”，作者 %(author)s，%(licence)s，来自 <a href="%(url)s">Freesound</a>。'


# Data is shown as it is ------------------------------------------------------------------------

@pytest.mark.parametrize('data', [
    'カメラ（１）／写真', '/Volumes/ＤＩＳＫ／ＤＣＩＭ', 'テスト。ファイル：イチ', '／ｗｏｒｋ／ｒｅｃｏｒｄ　ｆｏｌｄｅｒ'])
def test_a_line_nothing_translates_is_shown_as_printed(data):
    # The full-width marks of a kana name or a full-width path are its own characters, not punctuation
    # left from a translation: they stay.
    assert translate_line(data) == data
    assert translate_text(data) == data


def test_a_value_of_a_translated_format_is_shown_as_printed():
    line = '正在卸载相机磁盘（不拔线）：ディスク（１）'
    assert translate_line(line) == ENGINE['正在卸载相机磁盘（不拔线）：%s'] % 'ディスク（１）'


def test_the_sony_usb_identities_seen_are_listed_without_cjk_marks():
    # transport.Session prints the identities it saw; one line on its own, as one 250 ms read can be.
    line = '认证后相机未进入服务模式（期间出现的 Sony USB 身份：0e8a, 0336）。'
    for shown in (translate_line(line), translate_text(line), translate_text(line + '\n')):
        assert not CJK.search(shown), shown
    source = (ROOT / 'src/camera_runtime/transport.py').read_text(encoding='utf-8')
    assert "'、'.join(seen)" not in source and "', '.join(seen)" in source


def test_the_windows_driver_devices_are_listed_without_cjk_marks():
    source = (ROOT / 'src/desktopapp/platforms/usb_drivers.py').read_text(encoding='utf-8')
    assert "'；'.join(detected)" not in source and "'; '.join(detected)" in source
    line = ('未找到相机的海量存储身份 054C:0E8A，请在相机选择“海量存储”后重新连接。当前检测：VID_054C&PID_0E8A Sony; '
            'VID_054C&PID_0336 Sony。完整设备／接口信息已保存，不会为未知 PID 自动更换驱动。')
    assert not CJK.search(translate_text(line))


# One lookup ----------------------------------------------------------------------------------

def test_the_key_and_the_english_come_from_one_lookup():
    for text in ('  正在写入程序窗口批次 3/12  ', '正在写入程序窗口批次 3/12', '读取相机程序文件以识别固件编译版本（只读）。'):
        key, english = engine_text.lookup(text.strip())
        assert engine_text.source(text) == key
        assert translate_text(text).strip() == english
    assert engine_text.lookup('没有这条消息') is None and engine_text.source('没有这条消息') is None


# The specifiers the catalogues use ----------------------------------------------------------------

def test_the_catalogues_use_only_d_f_and_s():
    used = {match.group() for table in (STRINGS, ENGINE) for key in table if key != FREESOUND
            for match in re.finditer(r'%[^%\s，。：；（）]*?[a-zA-Z%]', key)}
    assert used <= {'%s', '%d', '%.0f', '%.1f', '%.2f', '%.3f'}
    assert all(engine_text.SPECIFIER.fullmatch(specifier) for specifier in used)
    assert not engine_text.SPECIFIER.search('%(title)s %% %x %r')


def test_the_sound_credit_is_no_display_entry():
    # window.sound_page fills it with named fields after tr(); display() never sees it.
    assert FREESOUND in STRINGS and FREESOUND in engine_text.NOT_DISPLAYED
    assert FREESOUND not in engine_text.EXACT
    assert all(FREESOUND != found.source for found in engine_text.FORMATS)
    assert sorted(re.findall(r'%\((\w+)\)s', STRINGS[FREESOUND])) == ['author', 'licence', 'title', 'url']


# A build's key is shown as its label, without looktool -------------------------------------------

def test_the_build_labels_are_buildprofiles():
    # engine_text keeps its own copy so display() never imports looktool (R63).
    assert engine_text.BUILD_LABELS == {build.key: build.label_zh for build in BUILDS}


def test_display_works_on_a_first_source_launch_before_looktool_is_importable():
    # R63: on a first source launch only src/ is on the path until setup_runtime(); the window shows
    # engine text before that (window.sound_presets while it opens, shell.warn). A catalogued format,
    # with a build key as its value and with plain data, must read in English without looktool.
    public, body = BUILDS
    lines = [JOB_OTHER_BUILD % (body.key, public.key), '正在卸载相机磁盘（不拔线）：ディスク（１）']
    script = textwrap.dedent('''
        import importlib.util, json, sys
        from pathlib import Path
        sys.path.insert(0, str(Path.cwd() / 'src'))
        assert importlib.util.find_spec('looktool') is None
        from desktopapp import engine_text, i18n
        i18n.configure('en')
        print(json.dumps([engine_text.display(line) for line in json.loads(sys.argv[1])]))
        assert 'looktool' not in sys.modules
    ''')
    environment = dict(os.environ)
    environment.pop('PYTHONPATH', None)
    result = subprocess.run([sys.executable, '-c', script, json.dumps(lines)], cwd=ROOT, env=environment,
                            capture_output=True, text=True, encoding='utf-8', timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
    assert json.loads(result.stdout) == [
        'This job was planned for Sony 2.01 (camera build, 23 Sep 2025), but the camera now runs Sony 2.01 '
        '(public update). Nothing was verified or written.',
        ENGINE['正在卸载相机磁盘（不拔线）：%s'] % 'ディスク（１）']
