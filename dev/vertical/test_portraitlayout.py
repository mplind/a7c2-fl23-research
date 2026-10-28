"""Portrait image reference changes preserve corresponding landscape tables."""
from pathlib import Path
import struct
import sys

import pytest

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'src/vertical'))
from verticaltool import portraitlayout

PAIR=((0,128,64,0x02000f96),)


def fixture():
    raw=bytearray(256)
    for root,size in ((0,0x028001e0),(128,0x01e00280)):
        struct.pack_into('<6I',raw,root,0x82,0xb81,0x250e,0,0,size)
        struct.pack_into('<I',raw,root+64,0x02000f96)
    return bytes(raw)


def test_portrait_reference_has_an_inverse_and_landscape_stays_original():
    source=fixture();target,windows=portraitlayout.references(source,True,pairs=PAIR)
    assert len(windows)==1 and windows[0]['offset']==64
    assert target[128:]==source[128:]
    assert portraitlayout.references(target,True,pairs=PAIR)==(target,[])
    assert portraitlayout.references(target,False,pairs=PAIR)[0]==source


def test_layout_and_landscape_conflicts_stop_planning():
    raw=bytearray(fixture());raw[128]^=1
    with pytest.raises(ValueError,match='canvas differs'):
        portraitlayout.references(raw,True,pairs=PAIR)
    raw=bytearray(fixture());raw[192]^=1
    with pytest.raises(ValueError,match='Landscape image'):
        portraitlayout.references(raw,True,pairs=PAIR)


def stock_layout():
    """An appFw.so-sized buffer holding just what canonical_windows checks: every canvas root, every
    original image ID, portrait and landscape, and both stock gauge blocks."""
    from verticaltool import portraitgauge
    raw=bytearray(max(max(p,l)+max(d,24) for p,l,d,_ in portraitlayout.PAIRS)+4)
    for portrait,landscape,delta,original in portraitlayout.PAIRS:
        for root,size in ((portrait,0x028001e0),(landscape,0x01e00280)):
            struct.pack_into('<6I',raw,root,0x82,0xb81,0x250e,0,0,size)
            struct.pack_into('<I',raw,root+delta,original)
    raw[portraitgauge.OFFSET:portraitgauge.OFFSET+len(portraitgauge.BEFORE)]=portraitgauge.BEFORE
    at=portraitgauge.VERTICAL_OFFSET
    raw[at:at+len(portraitgauge.VERTICAL_BEFORE)]=portraitgauge.VERTICAL_BEFORE
    return bytes(raw)


def test_stock_windows_are_the_planned_windows_without_program_bytes():
    """stock_windows needs no appFw.so: it is what canonical_windows plans on stock, in its order."""
    planned=portraitlayout.canonical_windows(stock_layout())
    assert portraitlayout.stock_windows()==[(row['offset'],bytes.fromhex(row['before_hex'])) for row in planned]
    assert len(planned)==19
