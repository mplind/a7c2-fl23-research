"""Draw the A7C II Tools app icon: one sunset seen through six film looks in a 35mm slide mount.

python dev/desktop/icon/make_icon.py [output folder]

writes AppIcon.icns (by default beside this script, where desktop.spec and the window take it from).
macOS only: headless Google Chrome draws the SVG, whose filters need a browser engine; sips scales it
and iconutil packs the iconset. With the Chrome that drew the approved icon (October 2026) the output
is byte-identical to the committed AppIcon.icns.
"""
import argparse
import os
from pathlib import Path
import signal
import subprocess
import tempfile
import time

CHROME = Path('/Applications/Google Chrome.app/Contents/MacOS/Google Chrome')

W = H = 1024
MOUNT = (100, 100, 824, 824, 186)          # Apple's macOS icon grid: 824 body, 100 margin
WINDOW = (660, 440, 34)                    # 3:2, like a 36 x 24 mm frame
# Each look: sky top, sky horizon, sun, glow, far hills, near hills, water, ground, glint
LOOKS = [
    ('Kodachrome',     '#0f3f96', '#ffb35c', '#ffe08a', '#ff9a3c', '#8c3a22', '#3a170e', '#123f86', '#1c0b07', '#ffd27a'),
    ('Portra 400',     '#86aac6', '#f8cfae', '#fff3dc', '#ffcf9f', '#a3858a', '#66545a', '#a7c0d2', '#433739', '#fff0d8'),
    ('Velvia',         '#3a1a74', '#ff5c86', '#ffe46e', '#ff3f74', '#17803f', '#0a4421', '#5e2aa0', '#062411', '#ffd9a8'),
    ('Provia',         '#2b6cb8', '#d3e7f5', '#fffaf0', '#ffe6b4', '#4f7d61', '#284733', '#5c98cc', '#18281d', '#fff6dc'),
    ('Classic Chrome', '#4d6c76', '#cdc5aa', '#f2e9cc', '#dccb9f', '#6f6c5d', '#3a3932', '#6f8b8d', '#22211d', '#efe6c8'),
    ('CineStill 800T', '#082f44', '#2c8c9a', '#ffe2c0', '#ff3b30', '#0f3944', '#06202a', '#1b6c7a', '#04141a', '#ff6a4d'),
]
SUN = (0.70, 0.47)                         # sun position as fractions of the window


def svg():
    mx, my, mw, mh, mr = MOUNT
    ww, wh, wr = WINDOW
    wx, wy = (W - ww) // 2, (H - wh) // 2 - 6
    bw = ww / len(LOOKS)
    sx, sy = wx + ww * SUN[0], wy + wh * SUN[1]
    horizon = wy + wh * 0.64
    defs, bands = [], []
    for i, (_, top, hor, sun, glow, far, near, water, ground, glint) in enumerate(LOOKS):
        x = wx + i * bw
        defs.append(
            f'<clipPath id="band{i}"><rect x="{x:.2f}" y="{wy}" width="{bw + 0.6:.2f}" height="{wh}"/></clipPath>'
            f'<linearGradient id="sky{i}" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="{top}"/>'
            f'<stop offset="1" stop-color="{hor}"/></linearGradient>'
            f'<radialGradient id="glow{i}"><stop offset="0" stop-color="{glow}" stop-opacity="0.9"/>'
            f'<stop offset="1" stop-color="{glow}" stop-opacity="0"/></radialGradient>'
            f'<linearGradient id="water{i}" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="{hor}"/>'
            f'<stop offset="1" stop-color="{water}"/></linearGradient>'
            f'<radialGradient id="glint{i}" cx="0.5" cy="0.15" r="0.6"><stop offset="0" stop-color="{glint}" stop-opacity="0.95"/>'
            f'<stop offset="1" stop-color="{glint}" stop-opacity="0"/></radialGradient>')
        bands.append(f'''<g clip-path="url(#band{i})">
<rect x="{wx}" y="{wy}" width="{ww}" height="{wh}" fill="url(#sky{i})"/>
<circle cx="{sx}" cy="{sy}" r="170" fill="url(#glow{i})"/>
<circle cx="{sx}" cy="{sy}" r="44" fill="{sun}"/>
<path d="M{wx} {horizon - 34} C {wx + ww * .16} {horizon - 78}, {wx + ww * .33} {horizon - 58}, {wx + ww * .47} {horizon - 26} S {wx + ww * .66} {horizon - 6}, {wx + ww} {horizon - 30} L {wx + ww} {horizon} L {wx} {horizon} Z" fill="{far}"/>
<rect x="{wx}" y="{horizon}" width="{ww}" height="{wy + wh - horizon}" fill="url(#water{i})"/>
<ellipse cx="{sx}" cy="{horizon + 52}" rx="34" ry="64" fill="url(#glint{i})"/>
<path d="M{wx} {wy + wh * .86} C {wx + ww * .18} {wy + wh * .79}, {wx + ww * .36} {wy + wh * .82}, {wx + ww * .52} {wy + wh * .90} S {wx + ww * .86} {wy + wh * .88}, {wx + ww} {wy + wh * .84} L {wx + ww} {wy + wh} L {wx} {wy + wh} Z" fill="{near}"/>
<path d="M{wx} {wy + wh * .95} C {wx + ww * .3} {wy + wh * .91}, {wx + ww * .7} {wy + wh * .98}, {wx + ww} {wy + wh * .93} L {wx + ww} {wy + wh} L {wx} {wy + wh} Z" fill="{ground}"/>
</g>''')
    seams = ''.join(f'<line x1="{wx + i * bw:.2f}" y1="{wy}" x2="{wx + i * bw:.2f}" y2="{wy + wh}" stroke="#000" stroke-opacity="0.22" stroke-width="2"/>'
                    for i in range(1, len(LOOKS)))
    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}">
<defs>
<linearGradient id="metal" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#f5f5f3"/><stop offset=".5" stop-color="#dcddda"/><stop offset="1" stop-color="#bdbeba"/></linearGradient>
<linearGradient id="rim" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#fff" stop-opacity=".95"/><stop offset="1" stop-color="#8d8e8a" stop-opacity=".9"/></linearGradient>
<linearGradient id="bevel" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#a9aaa6"/><stop offset="1" stop-color="#d7d8d4"/></linearGradient>
<filter id="shadow" x="-20%" y="-20%" width="140%" height="140%"><feGaussianBlur in="SourceAlpha" stdDeviation="14"/><feOffset dy="12"/><feComponentTransfer><feFuncA type="linear" slope=".32"/></feComponentTransfer><feMerge><feMergeNode/><feMergeNode in="SourceGraphic"/></feMerge></filter>
<filter id="brushed" x="0" y="0" width="100%" height="100%"><feTurbulence type="fractalNoise" baseFrequency=".002 .9" numOctaves="2" seed="7"/><feColorMatrix type="saturate" values="0"/><feComponentTransfer><feFuncA type="linear" slope=".09"/></feComponentTransfer><feComposite in2="SourceGraphic" operator="in"/></filter>
<filter id="grain" x="0" y="0" width="100%" height="100%"><feTurbulence type="fractalNoise" baseFrequency="1.1" seed="3"/><feColorMatrix type="saturate" values="0"/><feComponentTransfer><feFuncA type="linear" slope=".14"/></feComponentTransfer><feComposite in2="SourceGraphic" operator="in"/></filter>
<filter id="inset" x="-10%" y="-10%" width="120%" height="120%"><feOffset in="SourceAlpha" dy="6" result="off"/><feGaussianBlur in="off" stdDeviation="7" result="blur"/><feComposite in="SourceAlpha" in2="blur" operator="out" result="inner"/><feFlood flood-color="#000" flood-opacity=".6"/><feComposite in2="inner" operator="in"/></filter>
<clipPath id="window"><rect x="{wx}" y="{wy}" width="{ww}" height="{wh}" rx="{wr}"/></clipPath>
{''.join(defs)}
</defs>
<g filter="url(#shadow)">
<rect x="{mx}" y="{my}" width="{mw}" height="{mh}" rx="{mr}" fill="url(#metal)"/>
<rect x="{mx}" y="{my}" width="{mw}" height="{mh}" rx="{mr}" fill="#000" filter="url(#brushed)"/>
<rect x="{mx + 1.5}" y="{my + 1.5}" width="{mw - 3}" height="{mh - 3}" rx="{mr - 1.5}" fill="none" stroke="url(#rim)" stroke-width="3"/>
</g>
<rect x="{wx - 14}" y="{wy - 14}" width="{ww + 28}" height="{wh + 28}" rx="{wr + 12}" fill="url(#bevel)"/>
<g clip-path="url(#window)">{''.join(bands)}
<rect x="{wx}" y="{wy}" width="{ww}" height="{wh}" fill="#000" filter="url(#grain)"/>{seams}
<rect x="{wx}" y="{wy}" width="{ww}" height="{wh}" fill="#fff" filter="url(#inset)"/>
</g>
<rect x="{wx}" y="{wy}" width="{ww}" height="{wh}" rx="{wr}" fill="none" stroke="#000" stroke-opacity=".35" stroke-width="2"/>
<rect x="{W / 2 - 34}" y="{my + 46}" width="68" height="10" rx="5" fill="#a7a8a4"/>
<rect x="{W / 2 - 34}" y="{my + mh - 56}" width="68" height="10" rx="5" fill="#a7a8a4"/>
</svg>'''


SCALES = (16, 32, 128, 256, 512)           # the iconset's sizes, each also at @2x
PNG_END = bytes.fromhex('0000000049454e44ae426082')  # a PNG's closing IEND chunk


def draw(text, png, work):
    """Draw the SVG `text` on a transparent W x H page into `png` with headless Chrome. Chrome can hang
    on exit, so it runs in its own process group with its own profile, and the group is stopped once
    the image is complete."""
    page = work / 'icon.html'
    page.write_text('<!doctype html><html><head><meta charset="utf-8"><style>html,body{margin:0;'
                    'background:transparent}</style></head><body>' + text + '</body></html>', encoding='utf-8')
    chrome = subprocess.Popen([str(CHROME), '--headless=new', '--disable-gpu', '--hide-scrollbars',
                               '--user-data-dir=' + str(work / 'chrome-profile'),
                               '--default-background-color=00000000', '--window-size=%d,%d' % (W, H),
                               '--screenshot=' + str(png), page.as_uri()],
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    try:
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline and not (png.is_file() and png.read_bytes().endswith(PNG_END)):
            if chrome.poll() is not None and not png.is_file():
                break
            time.sleep(.2)
    finally:
        try:
            os.killpg(chrome.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        chrome.wait(timeout=30)
    if not (png.is_file() and png.read_bytes().endswith(PNG_END)):
        raise RuntimeError('Chrome did not draw the icon: ' + str(png))


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('output', type=Path, nargs='?', default=Path(__file__).resolve().parent)
    output = parser.parse_args().output.resolve()
    with tempfile.TemporaryDirectory(prefix='a7c2-icon-') as temporary:
        work = Path(temporary)
        png = work / 'icon-1024.png'
        draw(svg(), png, work)
        iconset = work / 'AppIcon.iconset'
        iconset.mkdir()
        for size in SCALES:
            for name, pixels in (('icon_%dx%d.png' % (size, size), size), ('icon_%dx%d@2x.png' % (size, size), 2 * size)):
                subprocess.run(['/usr/bin/sips', '-z', str(pixels), str(pixels), str(png), '--out', str(iconset / name)],
                               check=True, stdout=subprocess.DEVNULL)
        output.mkdir(parents=True, exist_ok=True)
        subprocess.run(['/usr/bin/iconutil', '-c', 'icns', str(iconset), '-o', str(output / 'AppIcon.icns')], check=True)
    print('wrote', output / 'AppIcon.icns')


if __name__ == '__main__':
    main()
