"""Keep Mach-O executables that cannot take a code signature out of PyInstaller's signing.

PyInstaller ad-hoc signs every collected BINARY, and codesign appends a 16-byte
LC_CODE_SIGNATURE after the existing load commands. Zig 0.13.0 for Intel macOS
leaves only 8 bytes there before __text, so signing overwrites machine code and
every clang compile segfaults. Collected as DATA instead, the executable is copied
unchanged into Contents/Resources and sealed as a resource of the signed bundle.
"""
import struct

MH_MAGIC_64=0xfeedfacf
LC_SEGMENT_64,LC_CODE_SIGNATURE=0x19,0x1d
HEADER=struct.Struct('<8I')              # mach_header_64
LOAD_COMMAND=struct.Struct('<II')        # cmd, cmdsize
SEGMENT=struct.Struct('<II16sQQQQiiII')  # segment_command_64; field 9 is nsects
SECTION=struct.Struct('<16s16sQQ8I')     # section_64; field 4 is the file offset
SIGNATURE_COMMAND_SIZE=16                # linkedit_data_command


def signing_would_corrupt(path):
    """True when adding a code signature would overwrite the binary's code."""
    with open(path,'rb') as stream:
        header=stream.read(HEADER.size)
        if len(header)!=HEADER.size or HEADER.unpack(header)[0]!=MH_MAGIC_64:
            raise ValueError('Not a 64-bit little-endian Mach-O: '+str(path))
        count,size=HEADER.unpack(header)[4:6]
        commands=stream.read(size)
    truncated=ValueError('Mach-O load commands are truncated: '+str(path))
    if len(commands)!=size:raise truncated
    signed=False;offsets=[];offset=0
    for _ in range(count):
        if offset+LOAD_COMMAND.size>size:raise truncated
        command,length=LOAD_COMMAND.unpack_from(commands,offset)
        if length<LOAD_COMMAND.size or offset+length>size:raise truncated
        if command==LC_CODE_SIGNATURE:signed=True
        elif command==LC_SEGMENT_64:
            sections=SEGMENT.unpack_from(commands,offset)[9]
            if SEGMENT.size+SECTION.size*sections>length:raise truncated
            for index in range(sections):
                start=SECTION.unpack_from(commands,offset+SEGMENT.size+SECTION.size*index)[4]
                # Zero-fill sections (__bss, __common) have no bytes in the file.
                if start:offsets.append(start)
        offset+=length
    if not offsets:return False
    room=min(offsets)-(HEADER.size+size)
    if room<0:raise ValueError('Mach-O load commands overlap its code; an earlier signature overwrote it: '+str(path))
    return not signed and room<SIGNATURE_COMMAND_SIZE


def keep_unsigned(binaries,datas,name='ziglang/zig'):
    """Return (binaries, datas) with `name` collected as DATA when signing would corrupt it."""
    entries=[entry for entry in binaries if entry[0]==name]
    listed_as_data=any(entry[0]==name for entry in datas)
    if not entries:
        if listed_as_data:return binaries,datas
        raise ValueError('PyInstaller did not collect '+name)
    if not signing_would_corrupt(entries[0][1]):return binaries,datas
    binaries=[entry for entry in binaries if entry[0]!=name]
    return binaries,(datas if listed_as_data else datas+[(name,entries[0][1],'DATA')])
