"""Native archive composition without PyInstaller, signing tools or USB."""
import importlib.util
import io
import json
from pathlib import Path
import platform
import shutil
import subprocess
from unittest.mock import patch
import zipfile
import pytest
import sys

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'dev/desktop'))
import profilepack


def library_fixture(root):
    from test_compile_dcp_offline import dcp
    from looktool import lookfile,rawidentity
    library=root/'desktop-assets/profile-library-v1';rows=[]
    for group,stem in profilepack.PAIRS:
        source=library/group/(stem+'.dcp');source.parent.mkdir(parents=True,exist_ok=True)
        dcp(source)
        output=source.with_suffix('.a7look')
        lookfile.write(output,'Fixture',bytes(1215),method='fixture',attribution='test',
            raw_profile=rawidentity.descriptor(source))
        rows.append(dict(dcp=source.relative_to(library).as_posix(),a7look=output.relative_to(library).as_posix(),
            independent_prediction=dict(RGB_MAE_8bit=0,RGB_P95_8bit=0)))
    import json
    (library/'catalog.json').write_text(json.dumps(dict(profiles=rows)))
    return library


def module(name):
    spec=importlib.util.spec_from_file_location('desktop_'+name,ROOT/('dev/desktop/'+name+'.py'))
    value=importlib.util.module_from_spec(spec);spec.loader.exec_module(value);return value


assets=module('prepare_assets')
build=module('build')


def test_pack_export_import_preserves_six_files_and_notices(tmp_path):
    before=tmp_path/'before';folder=before/'desktop-assets/presets/default-six-v1';folder.mkdir(parents=True)
    for name in assets.PRESET_NAMES:(folder/name).write_bytes(name.encode())
    library_fixture(before)
    (folder/'private-photo.ARW').write_bytes(b'not-distributable')
    archive=assets.export_presets(tmp_path/'presets.zip',before)
    after=assets.import_presets(archive,tmp_path/'after')
    assert sorted(p.name for p in after.iterdir())==sorted(assets.PRESET_NAMES)
    for name in assets.PRESET_NAMES:assert (after/name).read_bytes()==(folder/name).read_bytes()
    assert len(profilepack.files(tmp_path/'after'))==37


def test_existing_windows_zip_extracts_data_only(tmp_path):
    library_fixture(tmp_path/'fixture')
    source=io.BytesIO()
    with zipfile.ZipFile(source,'w') as z:
        for name in assets.PRESET_NAMES:z.writestr('A7C2Tools/_internal/desktop-assets/presets/default-six-v1/'+name,b'asset')
        z.writestr('A7C2Tools/A7C2Tools.exe',b'windows-executable')
        z.writestr('../../outside',b'not-data')
        for name,path in profilepack.files(tmp_path/'fixture').items():z.write(path,'A7C2Tools/Profiles/'+name)
    source.seek(0)
    target=assets.import_presets(source,tmp_path)
    assert len(list(target.iterdir()))==len(assets.PRESET_NAMES)
    assert not list(tmp_path.rglob('*.exe'))


def test_missing_pack_notice_does_not_replace_existing_assets(tmp_path):
    target=tmp_path/'desktop-assets/presets/default-six-v1';target.mkdir(parents=True)
    (target/'slot1.a7look').write_bytes(b'existing')
    source=io.BytesIO()
    with zipfile.ZipFile(source,'w') as z:z.writestr('default-six-v1/slot1.a7look',b'incomplete')
    source.seek(0)
    with pytest.raises(KeyError):assets.import_presets(source,tmp_path)
    assert (target/'slot1.a7look').read_bytes()==b'existing'


def test_windows_output_path_unchanged(tmp_path):
    fixture=tmp_path/'fixture';library_fixture(fixture)
    exe=tmp_path/'A7C2Tools/A7C2Tools.exe';exe.parent.mkdir();exe.write_bytes(b'test')
    (exe.parent/'a7c2-diagnostics.zip').write_bytes(b'private local diagnostic')
    with patch.object(build,'profile_files',side_effect=lambda:profilepack.files(fixture)):
        result=build.make_windows_zip(tmp_path,'public')
    assert result.name=='A7C2Tools-Windows-x64.zip'
    with zipfile.ZipFile(result) as z:
        assert z.read('A7C2Tools/A7C2Tools.exe')==b'test'
        assert len([n for n in z.namelist() if n.endswith('.dcp')])==18
        assert len([n for n in z.namelist() if n.startswith('A7C2Tools/Profiles/') and n.endswith('.a7look')])==18
        assert not any('diagnostics' in n for n in z.namelist())


def test_build_library_rejects_missing_or_mismatched_pair(tmp_path):
    library=library_fixture(tmp_path)
    row=profilepack.PAIRS[0];source=library/row[0]/(row[1]+'.dcp')
    original=source.read_bytes();source.write_bytes(b'wrong DCP')
    with pytest.raises(ValueError,match='source differs'):profilepack.files(tmp_path)
    source.write_bytes(original);source.with_suffix('.a7look').unlink()
    with pytest.raises(FileNotFoundError):profilepack.files(tmp_path)


def test_mono_pairs_are_excluded_as_pairs_when_quality_is_insufficient(tmp_path):
    import json
    library=library_fixture(tmp_path);catalog=library/'catalog.json'
    doc=json.loads(catalog.read_text())
    mono=next(r for r in doc['profiles'] if (r['dcp'],r['a7look']) in profilepack.OPTIONAL)
    mono['independent_prediction']['RGB_MAE_8bit']=8.6
    catalog.write_text(json.dumps(doc))
    with pytest.raises(ValueError,match='Monochrome profile'):profilepack.files(tmp_path)
    doc['profiles']=[r for r in doc['profiles'] if (r['dcp'],r['a7look']) not in profilepack.OPTIONAL]
    catalog.write_text(json.dumps(doc))
    files=profilepack.files(tmp_path)
    assert len([name for name in files if name.endswith('.dcp')])==15
    assert len([name for name in files if name.endswith('.a7look')])==15


def test_dmg_has_fresh_staging_and_arch_specific_filename(tmp_path):
    app=tmp_path/'A7C2Tools.app';app.mkdir();(app/'file').write_bytes(b'app')
    old=tmp_path/'dmg-contents';old.mkdir();(old/'stale').write_bytes(b'stale')
    def command(args,**kwargs):
        if args[:2]==['hdiutil','create']:
            stage=Path(args[args.index('-srcfolder')+1])
            assert sorted(p.name for p in stage.iterdir())==['A7C2Tools.app','Applications']
            Path(args[-1]).write_bytes(b'dmg')
    def symlink(path,target,**kwargs):path.write_text(str(target))
    with patch.object(build.platform,'machine',return_value='arm64'), \
            patch.object(build.subprocess,'run',side_effect=command) as run, \
            patch.object(Path,'symlink_to',symlink):
        result=build.make_dmg(tmp_path,'public')
    assert result.name=='A7C2Tools-macOS-arm64.dmg'
    assert not list(tmp_path.glob('a7c2-dmg-*'))
    assert run.call_args.args[0]==['hdiutil','verify',str(result)]


posix_only=pytest.mark.skipif(sys.platform=='win32',reason='needs a POSIX shell and symlinks')
intel_mac=pytest.mark.skipif(sys.platform!='darwin' or platform.machine()!='x86_64',reason='Intel macOS Zig only')
# Stand-ins for the bundled compiler: find the -o argument, then write an ELF header there.
OUTPUT_ARG='out=\nwhile [ $# -gt 0 ]; do [ "$1" = -o ] && out=$2; shift; done\n'
AARCH64_ELF=OUTPUT_ARG+"printf '\\177ELF\\002\\001\\001\\000\\000\\000\\000\\000\\000\\000\\000\\000\\003\\000\\267\\000' > \"$out\"\n"
X86_64_ELF=AARCH64_ELF.replace('\\267','\\076')


def app_with_fake_zig(root,script):
    zig=root/'A7C2Tools.app/Contents/Frameworks/ziglang/zig'
    zig.parent.mkdir(parents=True)
    zig.write_text('#!/bin/sh\n'+script);zig.chmod(0o755)
    return root/'A7C2Tools.app'


def app_with_zig_package(root,package):
    """The layout PyInstaller builds for unsigned Zig: Frameworks/ziglang links to the package."""
    framework=root/'A7C2Tools.app/Contents/Frameworks';framework.mkdir(parents=True)
    (framework/'ziglang').symlink_to(package,target_is_directory=True)
    return root/'A7C2Tools.app'


@posix_only
def test_zig_check_accepts_an_aarch64_library(tmp_path):
    build.check_bundled_zig(app_with_fake_zig(tmp_path,AARCH64_ELF))


@posix_only
@pytest.mark.parametrize('script',[X86_64_ELF,'exit 0\n'],ids=['x86_64-output','no-output'])
def test_zig_check_rejects_output_that_is_not_an_aarch64_library(tmp_path,script):
    with pytest.raises(RuntimeError,match='AArch64'):build.check_bundled_zig(app_with_fake_zig(tmp_path,script))


@posix_only
def test_zig_check_reports_a_crashing_compiler(tmp_path):
    app=app_with_fake_zig(tmp_path,'echo "Segmentation fault: 11" >&2\nexit 139\n')
    with pytest.raises(RuntimeError,match='exit 139.*Segmentation fault'):build.check_bundled_zig(app)


@pytest.mark.skipif(sys.platform!='darwin',reason='macOS bundle layout')
def test_zig_check_compiles_with_the_real_zig(tmp_path):
    package=Path(pytest.importorskip('ziglang').__file__).resolve().parent
    build.check_bundled_zig(app_with_zig_package(tmp_path,package))


@intel_mac
def test_zig_check_catches_zig_corrupted_by_codesign(tmp_path):
    package=Path(pytest.importorskip('ziglang').__file__).resolve().parent
    copy=tmp_path/'ziglang';copy.mkdir()
    (copy/'lib').symlink_to(package/'lib',target_is_directory=True)
    shutil.copyfile(package/'zig',copy/'zig');(copy/'zig').chmod(0o755)
    subprocess.run(['codesign','--sign','-',str(copy/'zig')],check=True,capture_output=True)
    with pytest.raises(RuntimeError,match='cannot compile'):
        build.check_bundled_zig(app_with_zig_package(tmp_path/'build',copy))


def fake_toolchain(events):
    """PyInstaller creates both outputs; codesign/hdiutil succeed without touching the host."""
    def command(args,**kwargs):
        if args[1:3]==['-m','PyInstaller']:
            events.append('PyInstaller')
            dist=Path(args[args.index('--distpath')+1])
            (dist/'A7C2Tools.app').mkdir(parents=True);(dist/'A7C2Tools').mkdir()
        else:
            events.append(args[0])
            if args[:2]==['hdiutil','create']:Path(args[-1]).write_bytes(b'dmg')
    return command


def run_main(tmp_path,host):
    events=[];output=tmp_path/'dist'
    with patch.object(build.sys,'platform',host), \
            patch.object(build.platform,'machine',return_value='x86_64'), \
            patch.object(build.sys,'argv',['build.py','--output',str(output),'--edition','public']), \
            patch.dict(build.os.environ,{'GITHUB_ACTIONS':''}), \
            patch.object(build,'profile_files',return_value={}), \
            patch.object(build,'check_bundled_zig',side_effect=lambda app:events.append(('zig check',app))), \
            patch.object(build.subprocess,'run',side_effect=fake_toolchain(events)):
        build.main()
    return output,events


@posix_only
def test_main_checks_bundled_zig_before_making_the_intel_dmg(tmp_path,capsys):
    output,events=run_main(tmp_path,'darwin')
    assert Path(json.loads(capsys.readouterr().out)['artifact'])==output/'A7C2Tools-macOS-x86_64.dmg'
    assert events[0]=='PyInstaller'
    assert events.index(('zig check',output/'A7C2Tools.app'))<events.index('hdiutil')


def test_main_on_windows_makes_the_zip_without_a_zig_check(tmp_path,capsys):
    output,events=run_main(tmp_path,'win32')
    assert Path(json.loads(capsys.readouterr().out)['artifact'])==output/'A7C2Tools-Windows-x64.zip'
    assert events==['PyInstaller']


def test_main_still_refuses_hosts_other_than_windows_and_macos(tmp_path):
    with patch.object(build.sys,'platform','linux'), \
            patch.object(build.sys,'argv',['build.py','--output',str(tmp_path)]), \
            patch.object(build.subprocess,'run') as run:
        with pytest.raises(RuntimeError,match='native Windows or macOS'):build.main()
    run.assert_not_called()


def test_the_spec_bundles_every_qt_module_the_source_imports():
    # The app's source ships as data, so PyInstaller never sees its imports: a Qt module
    # missing here imports fine from the source tree and fails only in the packaged app.
    import re
    used = set()
    for path in (ROOT / 'src').rglob('*.py'):
        text = path.read_text(encoding='utf-8')
        for names in re.findall(r'from PySide6 import ([^\n]+)', text):
            used |= {name.split(' as ')[0].strip() for name in names.split(',')}
        used |= set(re.findall(r'PySide6\.(Qt\w+)', text))
    spec = (ROOT / 'dev/desktop/desktop.spec').read_text(encoding='utf-8')
    assert sorted(used - set(re.findall(r"'PySide6\.(Qt\w+)'", spec))) == []


# The personal and public editions ----------------------------------------------------------------------

def run_edition(tmp_path, *extra, default='public', app_content=None):
    """(edition PyInstaller saw, printed result, commands run) of build.main on a Mac with `extra`
    arguments, where the edition is `default` unless they choose one; `app_content` adds files to the
    built app, {relative path: text}."""
    seen, events = [], []
    toolchain = fake_toolchain(events)
    def command(args, **kwargs):
        if args[1:3] == ['-m', 'PyInstaller']:
            seen.append(kwargs['env']['A7C2_EDITION'])
            toolchain(args, **kwargs)
            for relative, text in (app_content or {}).items():
                path = Path(args[args.index('--distpath') + 1]) / 'A7C2Tools.app' / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(text)
            return None
        return toolchain(args, **kwargs)
    output = tmp_path / 'dist'
    with patch.object(build.sys, 'platform', 'darwin'), \
            patch.object(build.platform, 'machine', return_value='x86_64'), \
            patch.object(build.sys, 'argv', ['build.py', '--output', str(output), *extra]), \
            patch.object(build.assets_check, 'default_edition', return_value=default) as default_edition, \
            patch.dict(build.os.environ, {}, clear=False) as environment, \
            patch.object(build, 'profile_files', return_value={}), \
            patch.object(build, 'check_bundled_zig'), \
            patch.object(build.subprocess, 'run', side_effect=command), \
            patch('sys.stdout', io.StringIO()) as printed:
        environment.pop('GITHUB_ACTIONS', None)
        build.main()
    default_edition.assert_called_once_with(build.ROOT)  # where this checkout has the personal assets
    return seen, json.loads(printed.getvalue()), events


@posix_only
@pytest.mark.parametrize('extra, default, edition', [
    ((), 'personal', 'personal'), ((), 'public', 'public'),
    (('--edition', 'public'), 'personal', 'public'), (('--edition', 'personal'), 'public', 'personal')])
def test_build_tells_the_spec_its_edition(tmp_path, extra, default, edition):
    seen, result, _ = run_edition(tmp_path, *extra, default=default)
    assert seen == [edition] and result['edition'] == edition
    suffix = '-personal' if edition == 'personal' else ''
    assert Path(result['artifact']).name == 'A7C2Tools-macOS-x86_64%s.dmg' % suffix


def test_build_refuses_an_edition_it_does_not_know(tmp_path):
    with patch.object(build.sys, 'argv', ['build.py', '--edition', 'release']), \
            patch.object(build.subprocess, 'run') as run, patch('sys.stderr', io.StringIO()):
        with pytest.raises(SystemExit):
            build.main()
    run.assert_not_called()



# Fail closed: CI, the built app, the package name ------------------------------------------------------

def test_build_refuses_the_personal_edition_on_github_actions(tmp_path):
    with patch.object(build.sys, 'platform', 'darwin'), \
            patch.object(build.sys, 'argv', ['build.py', '--output', str(tmp_path), '--edition', 'personal']), \
            patch.dict(build.os.environ, {'GITHUB_ACTIONS': 'true'}), \
            patch.object(build.subprocess, 'run') as run:
        with pytest.raises(RuntimeError, match='GitHub Actions'):
            build.main()
    run.assert_not_called()


@posix_only
@pytest.mark.parametrize('content', [
    {'Contents/Resources/desktop-assets/personal/film-looks-v1/look.a7look': 'look'},
    {'Contents/Resources/desktop-assets/somewhere/pack.json': '{"pack": "personal-six-v1", "looks": []}'},
    {'Contents/Resources/x/catalog.json': '{"personal_use_only": true, "looks": []}'},
])
def test_a_public_build_holding_a_personal_asset_makes_no_package(tmp_path, content):
    with pytest.raises(RuntimeError, match='personal assets, so no package was made') as refused:
        run_edition(tmp_path, '--edition', 'public', app_content=content)
    assert 'Contents/Resources' in str(refused.value)
    assert not list((tmp_path / 'dist').glob('*.dmg'))


@posix_only
def test_the_personal_edition_is_not_scanned_and_names_its_package(tmp_path):
    content = {'Contents/Resources/desktop-assets/personal/presets/personal-six-v1/pack.json': '{"pack": "personal-six-v1"}'}
    _, result, events = run_edition(tmp_path, '--edition', 'personal', app_content=content)
    assert Path(result['artifact']).name == 'A7C2Tools-macOS-x86_64-personal.dmg'
    assert 'hdiutil' in events


@pytest.mark.parametrize('edition, name, volume', [
    ('public', 'A7C2Tools-macOS-arm64.dmg', 'A7C II Tools'),
    ('personal', 'A7C2Tools-macOS-arm64-personal.dmg', 'A7C II Tools (personal)')])
def test_the_dmg_name_and_volume_say_the_edition(tmp_path, edition, name, volume):
    app = tmp_path / 'A7C2Tools.app'; app.mkdir(); (app / 'file').write_bytes(b'app')
    created = []
    def command(args, **kwargs):
        if args[:2] == ['hdiutil', 'create']:
            created.append(args[args.index('-volname') + 1])
            Path(args[-1]).write_bytes(b'dmg')
    with patch.object(build.platform, 'machine', return_value='arm64'), \
            patch.object(build.subprocess, 'run', side_effect=command), \
            patch.object(Path, 'symlink_to', lambda path, target, **kwargs: path.write_text(str(target))):
        result = build.make_dmg(tmp_path, edition)
    assert result.name == name and created == [volume]


def test_the_windows_zip_name_says_the_edition(tmp_path):
    fixture = tmp_path / 'fixture'; library_fixture(fixture)
    exe = tmp_path / 'A7C2Tools/A7C2Tools.exe'; exe.parent.mkdir(); exe.write_bytes(b'test')
    with patch.object(build, 'profile_files', side_effect=lambda: profilepack.files(fixture)):
        assert build.make_windows_zip(tmp_path, 'personal').name == 'A7C2Tools-Windows-x64-personal.zip'


WORKFLOWS = [ROOT / '.github/workflows/release.yml', ROOT / '.github/workflows/desktop-preview.yml']


@pytest.mark.parametrize('workflow', WORKFLOWS, ids=lambda path: path.name)
def test_every_ci_build_is_the_public_edition(workflow):
    lines = [line for line in workflow.read_text(encoding='utf-8').splitlines() if 'dev/desktop/build.py' in line]
    assert lines and all(line.rstrip().endswith('dev/desktop/build.py --edition public') for line in lines)


@pytest.mark.parametrize('workflow', WORKFLOWS, ids=lambda path: path.name)
def test_ci_runs_the_personal_asset_guards(workflow):
    focused = [line for line in workflow.read_text(encoding='utf-8').splitlines()
               if 'python -m pytest' in line and 'dev/desktop/test_packaging.py' in line]
    assert len(focused) == 1 and 'dev/desktop/test_personal_assets.py' in focused[0].split()


@pytest.mark.parametrize('document', ['docs/en/development.md', 'docs/zh-CN/development.md'])
def test_the_development_guide_documents_the_edition(document):
    text = (ROOT / document).read_text(encoding='utf-8')
    for words in ('--edition public', '--edition personal', 'desktop-assets/personal', '-personal'):
        assert words in text, words
