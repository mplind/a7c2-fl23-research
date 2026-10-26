"""Native archive composition without PyInstaller, signing tools or USB."""
import importlib.util
import io
from pathlib import Path
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
        result=build.make_windows_zip(tmp_path)
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
        result=build.make_dmg(tmp_path)
    assert result.name=='A7C2Tools-macOS-arm64.dmg'
    assert not list(tmp_path.glob('a7c2-dmg-*'))
    assert run.call_args.args[0]==['hdiutil','verify',str(result)]


import struct
posix_symlinks=pytest.mark.skipif(sys.platform=='win32',reason='macOS bundle layout needs POSIX symlinks')


def macho(path,room,signed=False):
    """Minimal x86_64 Mach-O: __TEXT/__text starts `room` bytes after the load commands."""
    size=72+80+(16 if signed else 0)
    text=32+size+room
    section=struct.pack('<16s16sQQ8I',b'__text',b'__TEXT',0x100000000+text,8,text,0,0,0,0,0,0,0)
    commands=struct.pack('<II16sQQQQiiII',0x19,72+80,b'__TEXT',0x100000000,0x1000,0,0x1000,5,5,1,0)+section
    if signed:commands+=struct.pack('<4I',0x1d,16,0x2000,0x100)
    header=struct.pack('<8I',0xfeedfacf,0x01000007,3,2,2 if signed else 1,size,0x200085,0)
    path.write_bytes(header+commands+bytes(room)+b'UAWAVAUA')
    return path


def test_unsigned_zig_without_signature_room_needs_upstream_copy(tmp_path):
    # Zig 0.13.0 for Intel macOS: load commands end at 2360, __text starts at 2368.
    assert build.needs_unsigned_copy(macho(tmp_path/'zig',room=8)) is True


def test_room_for_a_signature_is_left_to_pyinstaller(tmp_path):
    assert build.needs_unsigned_copy(macho(tmp_path/'zig',room=16)) is False


def test_already_signed_zig_is_left_to_pyinstaller(tmp_path):
    # Apple Silicon Zig is linker-signed; re-signing replaces that command in place.
    assert build.needs_unsigned_copy(macho(tmp_path/'zig',room=8,signed=True)) is False


def test_non_macho_compiler_is_rejected(tmp_path):
    path=tmp_path/'zig';path.write_bytes(b'\x7fELF'+bytes(60))
    with pytest.raises(ValueError,match='Mach-O'):build.needs_unsigned_copy(path)


@pytest.mark.skipif(sys.platform!='darwin' or build.platform.machine()!='x86_64',reason='Intel macOS Zig wheel only')
def test_installed_intel_zig_0_13_has_no_signature_room():
    import ziglang
    zig=Path(ziglang.__file__).resolve().parent/'zig'
    if not zig.is_file():pytest.skip('ziglang executable not installed')
    assert build.needs_unsigned_copy(zig) is True


def pyinstaller_app(root):
    """PyInstaller's macOS layout: signed Zig in Frameworks, Resources links to it."""
    app=root/'A7C2Tools.app'
    framework=app/'Contents/Frameworks/ziglang/zig';framework.parent.mkdir(parents=True)
    framework.write_bytes(b'signature overwrote code');framework.chmod(0o755)
    resource=app/'Contents/Resources/ziglang/zig';resource.parent.mkdir(parents=True)
    resource.symlink_to('../../Frameworks/ziglang/zig')
    return app


@posix_symlinks
def test_keep_upstream_zig_seals_original_bytes_and_resigns_app(tmp_path):
    app=pyinstaller_app(tmp_path);upstream=macho(tmp_path/'upstream-zig',room=8);upstream.chmod(0o755)
    with patch.object(build.subprocess,'run') as run:build.keep_upstream_zig(app,upstream)
    resource=app/'Contents/Resources/ziglang/zig';framework=app/'Contents/Frameworks/ziglang/zig'
    assert not resource.is_symlink() and resource.read_bytes()==upstream.read_bytes()
    assert resource.stat().st_mode&0o111
    assert framework.is_symlink() and framework.resolve()==resource.resolve()
    run.assert_called_once_with(['codesign','--force','--sign','-',str(app)],check=True)


def fake_mac_toolchain(calls):
    """PyInstaller creates the app; codesign/hdiutil succeed without touching the host."""
    def command(args,**kwargs):
        calls.append(list(args))
        if args[1:3]==['-m','PyInstaller']:
            pyinstaller_app(Path(args[args.index('--distpath')+1]))
        elif args[:2]==['hdiutil','create']:Path(args[-1]).write_bytes(b'dmg')
    return command


def run_mac_main(tmp_path,upstream,calls):
    output=tmp_path/'dist'
    with patch.object(build.sys,'platform','darwin'), \
            patch.object(build.platform,'machine',return_value='x86_64'), \
            patch.object(build.sys,'argv',['build.py','--output',str(output)]), \
            patch.object(build,'profile_files',return_value={}), \
            patch.object(build,'upstream_zig',return_value=upstream), \
            patch.object(build.subprocess,'run',side_effect=fake_mac_toolchain(calls)):
        build.main()
    return output


@posix_symlinks
def test_main_packages_intel_mac_with_x86_64_dmg_and_upstream_zig(tmp_path,capsys):
    calls=[];upstream=macho(tmp_path/'upstream-zig',room=8)
    output=run_mac_main(tmp_path,upstream,calls)
    import json
    printed=json.loads(capsys.readouterr().out)
    assert Path(printed['artifact'])==output/'A7C2Tools-macOS-x86_64.dmg'
    assert printed['camera_io'] is False
    assert calls[0][1:3]==['-m','PyInstaller'] and calls[0][-1].endswith('desktop.spec')
    assert (output/'A7C2Tools.app/Contents/Resources/ziglang/zig').read_bytes()==upstream.read_bytes()
    # Re-seal the bundle before the DMG step verifies it.
    assert calls.index(['codesign','--force','--sign','-',str(output/'A7C2Tools.app')])<calls.index(
        ['codesign','--verify','--deep','--strict',str(output/'A7C2Tools.app')])


@posix_symlinks
def test_main_keeps_pyinstaller_zig_when_signature_fits(tmp_path,capsys):
    calls=[];output=run_mac_main(tmp_path,macho(tmp_path/'upstream-zig',room=8,signed=True),calls)
    framework=output/'A7C2Tools.app/Contents/Frameworks/ziglang/zig'
    assert not framework.is_symlink() and framework.read_bytes()==b'signature overwrote code'
    assert ['codesign','--force','--sign','-',str(output/'A7C2Tools.app')] not in calls


def test_main_still_refuses_hosts_other_than_windows_and_macos(tmp_path):
    with patch.object(build.sys,'platform','linux'), \
            patch.object(build.sys,'argv',['build.py','--output',str(tmp_path)]), \
            patch.object(build.subprocess,'run') as run:
        with pytest.raises(RuntimeError,match='native Windows or macOS'):build.main()
    run.assert_not_called()
