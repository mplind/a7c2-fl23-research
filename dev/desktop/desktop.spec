import json
from pathlib import Path
import sys
from PyInstaller.utils.hooks import collect_all

root = Path(SPECPATH).parents[1]
sys.path.insert(0,str(root/'dev/desktop'))
from profilepack import files as profile_files
import assets_check
version = {}
exec((root / 'src/desktopapp/__init__.py').read_text(encoding='utf-8'), version)
# The Finder and Dock icon (make_icon.py beside it redraws it), named once. The same file ships as data
# below, where the window loads it (desktopapp.paths.APP_ICON).
ICON = 'dev/desktop/icon/AppIcon.icns'
icon = str(root / ICON)
# personal or public. Under desktop-assets/, each edition ships only the folders it knows
# (assets_check.shipped): the public edition never ships the owner's personal root.
edition = assets_check.edition()
assets_check.require(root, edition)
# The package records its edition beside the app's files (desktopapp.paths.edition()).
edition_record = Path(workpath) / 'edition.json'
edition_record.parent.mkdir(parents=True, exist_ok=True)
edition_record.write_text(json.dumps({'edition': edition}), encoding='utf-8')
left_out = set()
datas, binaries, hidden = [], [], ['PySide6.QtCore', 'PySide6.QtGui', 'PySide6.QtSvg', 'PySide6.QtWidgets',
                                 'tarfile', 'lzma', 'bz2', 'zlib', 'urllib.request', 'wave', 'plistlib', 'backports.tarfile', 'zipfile', 'filecmp']
if sys.platform=='darwin':hidden.append('pwd')
for package in ('numpy', 'scipy', 'PIL', 'tifffile', 'yaml', 'elftools', 'usb',
                'libusb_package', 'Cryptodome', 'imageio_ffmpeg', 'ziglang', 'keystone', 'capstone', 'unicorn'):
    d, b, h = collect_all(package)
    datas.extend(d)
    binaries.extend(b)
    hidden.extend(h)

# Source keeps original __file__-relative native headers and asset paths.
for folder in ('src/desktopapp', 'src/camera_runtime', 'src/looks/looktool',
               'src/looks/assets', 'src/looks/native', 'src/fl23/native', 'src/fl23/assets',
               'src/vertical', 'src/shutter_sound', 'plugins', 'desktop-assets'):
    for source in (root / folder).rglob('*'):
        relative = source.relative_to(root)
        if relative.parts[:2]==('desktop-assets','profile-library-v1'):continue
        if relative.parts[0] == 'desktop-assets' and not assets_check.bundled(relative, edition):
            if source.is_file():
                left_out.add(assets_check.unlisted(relative, edition))
            continue
        if not source.is_file() or any(p in ('__pycache__', 'tests') for p in relative.parts):
            continue
        if sys.platform == 'darwin' and (relative.parts[:2] == ('desktop-assets', 'windows') or source.suffix.lower() in ('.exe', '.dll', '.pyd', '.bat', '.cmd')):
            continue
        if source.suffix.lower()=='.dcp' and relative.parts[:2]!=('desktop-assets','profile-library-v1'):
            continue
        if '.private.' in source.name or (source.suffix.lower() in ('.arw', '.hif', '.jpg', '.cube', '.pyc')
                                          and not assets_check.personal_sample(relative)):
            continue
        datas.append((str(source), str(relative.parent)))
if left_out:
    print('Left out of this %s package (not a known asset folder): %s' % (edition, ', '.join(sorted(left_out))))
datas.append((str(edition_record), '.'))
for relative,source in profile_files().items():
    datas.append((str(source),str(Path('desktop-assets/profile-library-v1')/Path(relative).parent)))
for name in ('desktop.py', 'LICENSE', 'README.md', 'README.zh-CN.md', 'desktop-requirements.txt',
             'dev/desktop/offline_smoke.py', 'docs/en/lut-formats.md', 'docs/zh-CN/lut-formats.md',
             'docs/en/notices.md', 'docs/zh-CN/notices.md', 'docs/licenses/a7c2-fl23-macos-MIT.txt',
             'calibration/a7c2-2.01.virtual.npz', ICON):
    datas.append((str(root / name), str(Path(name).parent)))

a = Analysis([str(root / 'dev/desktop/frozen_entry.py')], pathex=[],
             binaries=binaries, datas=datas, hiddenimports=hidden,
             excludes=['tkinter', 'matplotlib', 'pandas', 'IPython', 'pytest'])
if sys.platform == 'darwin':
    # Signing would overwrite Intel Zig's code; collect it unsigned (see machosign.py).
    from machosign import keep_unsigned
    a.binaries, a.datas = keep_unsigned(a.binaries, a.datas)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name='A7C2Tools', icon=icon,
          console=False, disable_windowed_traceback=False)
collection = COLLECT(exe, a.binaries, a.datas, name='A7C2Tools')
if sys.platform == 'darwin':
    app = BUNDLE(collection, name='A7C2Tools.app', icon=icon, bundle_identifier='io.github.QAQLeonard.A7C2Tools',
                 info_plist={'CFBundleShortVersionString': version['VERSION'],
                             'CFBundleVersion': version['VERSION'].rsplit('.', 1)[-1],
                             'LSMinimumSystemVersion': '14.0',
                             'NSHighResolutionCapable': True,
                             'NSUSBUsageDescription': 'Access your Sony A7C II for requested camera operations.'})
