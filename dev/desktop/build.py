"""Build on the native host; Windows output paths remain unchanged."""
import argparse
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import tempfile
import zipfile
from profilepack import files as profile_files
import assets_check

ROOT = Path(__file__).resolve().parents[2]
APP_NAME = 'A7C2Tools.app'
# A personal package says so in its file name and its DMG volume; a public one is named as before.
SUFFIX = {'public': '', 'personal': '-personal'}
VOLUME = {'public': 'A7C II Tools', 'personal': 'A7C II Tools (personal)'}
EM_AARCH64 = 183


def check_bundled_zig(app):
    """Compile a tiny AArch64 library with the app's own Zig before packaging it.

    codesign can leave Zig valid on disk yet broken (on Intel it overwrote code),
    and only a real compile shows that.
    """
    zig=Path(app)/'Contents/Frameworks/ziglang/zig'
    with tempfile.TemporaryDirectory(prefix='a7c2-zig-check-') as temporary:
        work=Path(temporary);source=work/'check.c';library=work/'check.so'
        source.write_text('int check(int x){return x+1;}\n',encoding='ascii')
        environment=dict(os.environ,ZIG_GLOBAL_CACHE_DIR=str(work/'cache'),ZIG_LOCAL_CACHE_DIR=str(work/'cache'))
        result=subprocess.run([str(zig),'cc','-target','aarch64-linux-gnu','-shared','-fPIC','-nostdlib',
                               '-o',str(library),str(source)],env=environment,capture_output=True,
                              text=True,encoding='utf-8',errors='replace',timeout=180)
        if result.returncode:
            raise RuntimeError('Bundled Zig cannot compile camera code (exit %d): %s'%(result.returncode,result.stderr[-2000:]))
        header=library.read_bytes()[:20] if library.is_file() else b''
        if header[:4]!=b'\x7fELF' or int.from_bytes(header[18:20],'little')!=EM_AARCH64:
            raise RuntimeError('Bundled Zig did not produce an AArch64 ELF library: '+str(zig))


def refuse_personal(output):
    """Refuse to package a public build whose app holds any personal asset (assets_check.personal_findings)."""
    found=[folder+'/'+path for folder in (APP_NAME,'A7C2Tools') if (Path(output)/folder).is_dir()
           for path in assets_check.personal_findings(Path(output)/folder)]
    if found:
        raise RuntimeError('This public build holds personal assets, so no package was made: '+', '.join(found[:20]))


def make_dmg(output,edition):
    output=Path(output).resolve()
    app=output/APP_NAME
    if not app.is_dir():raise FileNotFoundError(app)
    target=output/('A7C2Tools-macOS-'+platform.machine()+SUFFIX[edition]+'.dmg')
    # Temporary staging prevents files from older builds leaking into the DMG.
    with tempfile.TemporaryDirectory(prefix='a7c2-dmg-',dir=output) as temporary:
        staging=Path(temporary)
        shutil.copytree(app,staging/app.name,symlinks=True)
        (staging/'Applications').symlink_to('/Applications',target_is_directory=True)
        subprocess.run(['codesign','--verify','--deep','--strict',str(app)],check=True)
        subprocess.run(['hdiutil','create','-ov','-format','UDZO','-volname',
                        VOLUME[edition],'-srcfolder',str(staging),str(target)],check=True)
    subprocess.run(['hdiutil','verify',str(target)],check=True)
    return target


def make_windows_zip(output,edition):
    output=Path(output)
    target=output/('A7C2Tools-Windows-x64'+SUFFIX[edition]+'.zip')
    library=profile_files()
    for relative,source in library.items():
        dest=output/'A7C2Tools/Profiles'/relative
        dest.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(source,dest)
    shutil.copyfile(ROOT/'README.md',output/'A7C2Tools/README.md')
    shutil.copyfile(ROOT/'README.zh-CN.md',output/'A7C2Tools/README.zh-CN.md')
    shutil.copyfile(ROOT/'LICENSE',output/'A7C2Tools/LICENSE')
    with zipfile.ZipFile(target,'w',zipfile.ZIP_DEFLATED,compresslevel=6) as stream:
        for source in sorted((output/'A7C2Tools').rglob('*')):
            relative=source.relative_to(output/'A7C2Tools')
            # Users may save diagnostic ZIPs beside the executable. Never
            # redistribute those local files in the next development bundle.
            if relative.parts[0] not in ('A7C2Tools.exe','_internal','README.md','README.zh-CN.md','LICENSE','VERSION.txt'):continue
            if relative.parts[:3]==('_internal','desktop-assets','profile-library-v1'):continue
            if source.is_file():stream.write(source,source.relative_to(output))
        for relative,source in library.items():stream.write(source,'A7C2Tools/Profiles/'+relative)
    return target


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,default=ROOT/'dist')
    parser.add_argument('--edition',choices=assets_check.EDITIONS,default=assets_check.default_edition(ROOT),
                        help="personal ships the owner's personal assets (the default where they are present); "
                             'public leaves them out, as every release and CI build must')
    args=parser.parse_args()
    if args.edition=='personal' and os.environ.get('GITHUB_ACTIONS'):
        raise RuntimeError('The personal edition is never built on GitHub Actions; build with --edition public.')
    if sys.platform not in ('win32','darwin'):raise RuntimeError('Build on native Windows or macOS')
    output=args.output.resolve();output.mkdir(parents=True,exist_ok=True)
    profile_files()
    subprocess.run([sys.executable,'-m','PyInstaller','--noconfirm',
                    '--distpath',str(output),'--workpath',str(ROOT/'build/desktop'),
                    str(ROOT/'dev/desktop/desktop.spec')],cwd=ROOT,check=True,
                   env=dict(os.environ,A7C2_EDITION=args.edition))
    if args.edition=='public':refuse_personal(output)
    if sys.platform=='darwin':
        check_bundled_zig(output/APP_NAME)
        target=make_dmg(output,args.edition)
    else:target=make_windows_zip(output,args.edition)
    print(json.dumps(dict(artifact=str(target),bytes=target.stat().st_size,camera_io=False,edition=args.edition)))


if __name__=='__main__':main()
