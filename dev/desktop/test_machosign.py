"""Signature-room checks that keep PyInstaller from corrupting Zig on Intel Macs."""
from pathlib import Path
import platform
import re
import struct
import sys
import pytest

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'dev/desktop'))
import machosign

SEGMENT=struct.Struct('<II16sQQQQiiII')
SECTION=struct.Struct('<16s16sQQ8I')


def macho(path,room,signed=False,sections=('text',)):
    """x86_64 Mach-O whose __text starts `room` bytes after the load commands.

    `sections` orders the section table: 'text', 'zerofill' (file offset 0) and
    'later' (4 KiB after text), so the first code byte is the smallest non-zero offset.
    """
    size=SEGMENT.size+SECTION.size*len(sections)+(16 if signed else 0)
    text=32+size+room
    offsets={'text':text,'zerofill':0,'later':text+4096}
    table=b''.join(SECTION.pack(name.encode(),b'__TEXT',0x100000000+offsets[name],8,offsets[name],0,0,0,0,0,0,0)
                   for name in sections)
    commands=SEGMENT.pack(0x19,SEGMENT.size+len(table),b'__TEXT',0x100000000,0x1000,0,0x1000,5,5,len(sections),0)+table
    if signed:commands+=struct.pack('<4I',0x1d,16,0x2000,0x100)
    header=struct.pack('<8I',0xfeedfacf,0x01000007,3,2,2 if signed else 1,len(commands),0x200085,0)
    data=header+commands
    path.write_bytes(data+bytes(max(text-len(data),0))+b'UAWAVAUA')
    return path


@pytest.mark.parametrize('room,expected',[(0,True),(8,True),(15,True),(16,False),(64,False)])
def test_signature_needs_sixteen_free_bytes_before_code(tmp_path,room,expected):
    # Zig 0.13.0 for Intel macOS: load commands end at 2360 and __text starts at 2368.
    assert machosign.signing_would_corrupt(macho(tmp_path/'zig',room)) is expected


def test_already_signed_binary_is_resigned_in_place(tmp_path):
    # Apple Silicon Zig is linker-signed; codesign replaces that command and adds nothing.
    assert machosign.signing_would_corrupt(macho(tmp_path/'zig',room=8,signed=True)) is False


def test_signature_that_already_overwrote_code_is_rejected(tmp_path):
    with pytest.raises(ValueError,match='overlap'):
        machosign.signing_would_corrupt(macho(tmp_path/'zig',room=-8,signed=True))


@pytest.mark.parametrize('sections',[('later','zerofill','text'),('text','zerofill','later'),('zerofill','later','text')])
def test_first_code_byte_is_the_smallest_file_backed_section(tmp_path,sections):
    assert machosign.signing_would_corrupt(macho(tmp_path/'zig',room=8,sections=sections)) is True


@pytest.mark.parametrize('content',[b'',b'\xcf\xfa\xed\xfe'+bytes(6),b'\x7fELF'+bytes(60)])
def test_short_or_foreign_compiler_is_rejected_with_its_path(tmp_path,content):
    path=tmp_path/'zig';path.write_bytes(content)
    with pytest.raises(ValueError,match=re.escape(str(path))):machosign.signing_would_corrupt(path)


def test_load_commands_running_past_the_file_are_rejected(tmp_path):
    path=macho(tmp_path/'zig',room=8)
    path.write_bytes(path.read_bytes()[:40])
    with pytest.raises(ValueError,match='truncated'):machosign.signing_would_corrupt(path)


@pytest.mark.skipif(sys.platform!='darwin',reason='the macOS ziglang wheel ships a Mach-O zig')
def test_installed_zig_needs_unsigned_packaging_only_on_intel():
    ziglang=pytest.importorskip('ziglang')
    zig=Path(ziglang.__file__).resolve().parent/'zig'
    assert machosign.signing_would_corrupt(zig) is (platform.machine()=='x86_64')


def test_unsignable_zig_moves_from_binaries_to_data(tmp_path):
    zig=str(macho(tmp_path/'zig',room=8))
    usb=('libusb-1.0.dylib','/site/libusb-1.0.dylib','BINARY')
    header=('ziglang/lib/c.h','/site/ziglang/lib/c.h','DATA')
    binaries,datas=machosign.keep_unsigned([usb,('ziglang/zig',zig,'BINARY')],[header])
    assert binaries==[usb]
    assert datas==[header,('ziglang/zig',zig,'DATA')]


def test_signable_zig_stays_a_binary(tmp_path):
    binaries=[('ziglang/zig',str(macho(tmp_path/'zig',room=8,signed=True)),'BINARY')]
    assert machosign.keep_unsigned(binaries,[])==(binaries,[])


def test_zig_also_listed_as_data_is_not_duplicated(tmp_path):
    zig=str(macho(tmp_path/'zig',room=8))
    binaries,datas=machosign.keep_unsigned([('ziglang/zig',zig,'BINARY')],[('ziglang/zig',zig,'DATA')])
    assert binaries==[]
    assert datas==[('ziglang/zig',zig,'DATA')]


def test_zig_collected_only_as_data_is_left_alone(tmp_path):
    datas=[('ziglang/zig',str(macho(tmp_path/'zig',room=8)),'DATA')]
    assert machosign.keep_unsigned([],datas)==([],datas)


def test_missing_zig_stops_the_build():
    with pytest.raises(ValueError,match='ziglang/zig'):machosign.keep_unsigned([],[])
