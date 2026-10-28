"""The real-firmware fixtures named by A7C2_BUILD_FIXTURES, and the digests they must have.

The folder holds public-2.01/, body-2.01-20250923/ and hybrid-20261027/, each with appFw.so and
cpapp-b.bin. conftest.py serves them as the build_fixture_files and build_fixtures fixtures: they
skip when the variable is unset and fail when a file isn't the one recorded here.

A build's /usr/share/app name files are in its own resources/ folder when the build was captured from
a camera (camera_fingerprint.py), or else beside the read-only fixture folders, in
<A7C2_BUILD_FIXTURES>-resources/<build>/ (extract_resources.py writes the public build's there).
conftest.py serves them as build_resources. Offline only.
"""
import hashlib
from pathlib import Path
from types import SimpleNamespace

PROGRAMS = ('appFw.so', 'cpapp-b.bin')
SIZES = (99960744, 18090880)
# Full-file SHA-256 (appFw.so, cpapp-b.bin), verified on the camera on 28 Oct 2026.
FINDINGS = {
    'public-2.01': ('2ea02f7ecbc5bb917316fe8ef4ce5ffd87eb66efaae78ba2ce11420552df539b',
                    'f5a477588698ef965748903b8959a39ce4f59ffd4aee4d4234ef1670f56a1428'),
    'body-2.01-20250923': ('77fa856ed5812124ffec507857ec48af43159357b2c8a341cb15f3d5c1076d54',
                           '171f6d7c0b95c6bea3b64487d0b826f38a94ec92ca3984679a0ee2899e704efa'),
}
# The camera after the 27 Oct Factory Restore wrote public bytes into the body build
# (camera-check/20261028T043722Z/report.json).
HYBRID = ('4a75b330c13132674879e6838ae44e7a07467384454cdf4d393a376a00fd7b3e',
          '171f6d7c0b95c6bea3b64487d0b826f38a94ec92ca3984679a0ee2899e704efa')
DIGESTS = {**FINDINGS, 'hybrid-20261027': HYBRID}


def sha(data):
    return hashlib.sha256(data).hexdigest()


def read(folder):
    """Every fixture's programs under `folder`, by folder name, with their digests."""
    result = {}
    for name in DIGESTS:
        path = Path(folder) / name
        ap, cp = ((path / program).read_bytes() for program in PROGRAMS)
        result[name] = SimpleNamespace(folder=path, ap=ap, cp=cp, digests=(sha(ap), sha(cp)))
    return result


def mismatches(files):
    """One line for each fixture in `files` whose digests aren't the recorded ones."""
    return ['%s: %s, expected %s' % (name, files[name].digests, digests)
            for name, digests in DIGESTS.items() if files[name].digests != digests]


def resources_folder(folder, name):
    """Where fixture build `name` under `folder` keeps its name files: its own resources/ folder when
    there is one, else <folder>-resources/<name>/ beside the fixtures; None when neither exists."""
    folder = Path(folder)
    for candidate in (folder / name / 'resources', folder.with_name(folder.name + '-resources') / name):
        if candidate.is_dir():
            return candidate
    return None


def resources(folder, name, filenames):
    """{file name: bytes} of every name file in `filenames` for fixture build `name`, or None when the
    build has no name files. A folder lacking any of them is refused, naming the first few."""
    where = resources_folder(folder, name)
    if where is None:
        return None
    missing = [filename for filename in filenames if not (where / filename).is_file()]
    if missing:
        raise ValueError('%s lacks %d of its name files: %s' % (where, len(missing), ', '.join(missing[:3])))
    return {filename: (where / filename).read_bytes() for filename in filenames}
