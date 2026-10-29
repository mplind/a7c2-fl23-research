"""The real-firmware fixtures named by A7C2_BUILD_FIXTURES, and the digests they must have.

The folder holds public-2.01/, body-2.01-20250923/ and hybrid-20261027/, each with appFw.so and
cpapp-b.bin. conftest.py serves them as the build_fixture_files and build_fixtures fixtures: they
skip when the variable is unset and fail when a file isn't the one recorded here.

A build's /usr/share/app name files are in its own resources/ folder, or else beside the read-only
fixture folders, in <A7C2_BUILD_FIXTURES>-resources/<build>/: extract_resources.py writes the public
build's there, and a camera's go there from a checked camera_fingerprint.py capture, which itself always
writes to a new folder of its own, never into a fixture folder.
Each must have the SHA-256 recorded here, as the programs must; a build's name files are refused
until their digests are recorded. conftest.py serves them as build_resources. Offline only.
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
# SHA-256 of each /usr/share/app name file nameworker.filenames() lists, by build. public-2.01's are
# those extract_resources.py saved from Sony's 2.01 BODYDATA.DAT on 28 Oct 2026. body-2.01-20250923's
# come from the resources digests in camera_fingerprint.py's report.json, once its capture is checked.
RESOURCE_DIGESTS = {
    'public-2.01': {
        'string_arabic_horizontal.uxc': '416f6161596bcf84310a838f87743899bc3d946c16a0eeb441d6142092622335',
        'string_arabic_vertical.uxc': '4602afe8403faa91e7a5a4aab0e6d4f945339c1095287b1c3d7fe8a8a6ac92e9',
        'string_brazilianportuguese_horizontal.uxc': 'b0bf551ae8aa05e1a50bcfdcdec520de685b2ba4ee4a36f1fe13dbf9cae2a01f',
        'string_brazilianportuguese_vertical.uxc': '8c7d84446ef3903634c0d43b62d9a4225aa5bf79630834093773b184c00d79ad',
        'string_bulgarian_horizontal.uxc': '19c28a89cb8a5cbf315fec7bac21f0b96ce5fa148eafc84bfdff7cd09ec2da66',
        'string_bulgarian_vertical.uxc': '2bbdd449605d6c2d7e348e656c38c5857e21aa1026e66d654990246534095589',
        'string_canadianfrench_horizontal.uxc': '2ca4e47f6a4b84b54564c8735cee0a50c954bead35a2281b3969868734422472',
        'string_canadianfrench_vertical.uxc': '48a68238c800e7c16c4f0ef1d1e55c0523e31b1f4982a02bb912142db6802237',
        'string_croatian_horizontal.uxc': 'adbca52371be099be07f3cdb3173053669b6a82ff84b72baf54187bd90bf776a',
        'string_croatian_vertical.uxc': '096dcb1764fa30497fda7f10b58ecd15b7a8f2622b0001864319672b1534d775',
        'string_czech_horizontal.uxc': '1a4e5515ba591b6628bfc61fa6f883dd52c3da3effb55d46616fa7e34153833e',
        'string_czech_vertical.uxc': '5f53243997a466ac426c37e42dd78f8f900b8e6b812caae905d0763b69e5ddc2',
        'string_danish_horizontal.uxc': 'abbe3b134d1d71cb1d81729b4234784798e130acd08ea7e06f65131ce0aaac91',
        'string_danish_vertical.uxc': 'bdc9ed3371583303dd5c7f63fbd3ced1bf0033a2c6171e2bb0ff4ca53556408e',
        'string_dutch_horizontal.uxc': '9072a964edfd34c937b7fd8b4ea6202c102b7fb9e44ffa31706e0e97a852164f',
        'string_dutch_vertical.uxc': 'c1c43c0576292893be81414f05c1c858cf247f5e0fd07ab1785b9abb96ea7eff',
        'string_english_horizontal.uxc': '32cb6b966a5fa323539a6429b2135e142d4d8ab2603fcc9eec3d886d00d1bf27',
        'string_english_vertical.uxc': '8aa1c689d87fb792f8cfeb09b6b69cc93eb1456325a7fea936489391d695ffee',
        'string_finnish_horizontal.uxc': '0c5da544c20b285bc5ebb75ce75d86b12ffa5019b39b2bb8000fc05eac116b8d',
        'string_finnish_vertical.uxc': '9539e36f58982419c3125ab760078730d71dc09f17aa620f0a6afbd1041b1123',
        'string_french_horizontal.uxc': '5c5606d775e17041342607b673bd2f81d141f205f438c57fa81797938d8ea618',
        'string_french_vertical.uxc': '835bac9d51d253e68ccd28308efa77d5ad8cbb102bf71cd79776003e7e0cd07b',
        'string_german_horizontal.uxc': '8442f0c98379fe060f3c565b260a83f280ee08afc122cef192c85697b2239542',
        'string_german_vertical.uxc': '047ce1c586ff02db1130a9477940d7d5ed2f8224763f05dbc69dc49ffcfa01f2',
        'string_greek_horizontal.uxc': '0f7a2dad01f2ae0216c111b92cb1d56d3af00269373b3d67a602870ae230733f',
        'string_greek_vertical.uxc': '351be3bd9ca7b12a6fa554e84f5ca48090121596c7c421b8e129b1791f26a6b1',
        'string_hindi_horizontal.uxc': 'b240e611868b3b50d4c0ebb744fa470585f4d1ba18640cac85eec38939e3d3f6',
        'string_hindi_vertical.uxc': '5d287f332a89cdb9fb2bb772e12c1feb4cccc2e6a54c8581a245c0004fcd9ee0',
        'string_hungarian_horizontal.uxc': '9b8f7ca7313501104538ccaf5e696a8c29b2999536894add17ee48f984b60301',
        'string_hungarian_vertical.uxc': 'b08322445b796f6d33fe604b9a421a05b23d6d2e4c910283a2a5114066ff4fa8',
        'string_indonesia_horizontal.uxc': '0aa5251c2bda51acf5cf61ea0c4bc15a15d94176c5145db2c1065cc6dbfab684',
        'string_indonesia_vertical.uxc': 'f480a0ea540905e896b2bfae26efe2cc1f5c784218b381e6f78880cfe542d523',
        'string_italian_horizontal.uxc': 'cccdca98641d503cfd38fd9ccf93ce7219ae43f5421474e0d7547c971ac4efef',
        'string_italian_vertical.uxc': 'c41e18cd44e1d1e7df5d714e0de2164c2eca0567443efa4896ef511e561304be',
        'string_japanese_horizontal.uxc': '9b12152f43cae18db33a2d021fe2c862f7c8e08ba2cd919672c66725cc8d789f',
        'string_japanese_vertical.uxc': '10f3464e1c2d89a4d5c36925b6228623ff50efb81809ff572dba702c9ecfb16a',
        'string_korean_horizontal.uxc': 'f6cad4e8d52913d42a9864da5d2a6c9516a64e49c3314b2f6d528888de60b1e6',
        'string_korean_vertical.uxc': '6e2f4af2f4de554f687420707bf252a035694143fb6a4e1d0b6da830dcd14b4d',
        'string_malay_horizontal.uxc': 'eb5a4614132a574a22f454515dfa53cd696664bf629ba1748264e36fdfa5df40',
        'string_malay_vertical.uxc': 'cdce4ce5f074cb5510e6961d11c7ba115b0ffd4a6906af979c76d132220e228c',
        'string_norwegian_horizontal.uxc': '44f64082fde26e21d7283d2003f9a54985edd532e85e810798f670e347e7b964',
        'string_norwegian_vertical.uxc': '690deb2ffc2c99cba7e3d81928663c96fc13cc5d7221acc6239b51c91de08b6c',
        'string_persian_horizontal.uxc': 'a793d6ee764408ad983f6c9ca58415131a6784813c752700b1551593b1914e3a',
        'string_persian_vertical.uxc': '073486b253bf80b30e1e85398a41a682ee3a36002f0f6fd64810b05647572627',
        'string_polish_horizontal.uxc': '390b7f339bdc67dc5bbda7b41497b5b729e75e9444cd2baa6a49bd0cfd261511',
        'string_polish_vertical.uxc': 'd1097481b9e742c4bb62665356893f7df2d22997170b23812eb0ce35a53b4024',
        'string_portuguese_horizontal.uxc': '12b1a4dd022b80d3bce8b99b4d70dfd3faba5e37a57a0796ffa5948f89015476',
        'string_portuguese_vertical.uxc': 'cb65a90176c5fa8163f8b2f4b9df8f30b8af05640182759c66953c40c5823cc7',
        'string_romanian_horizontal.uxc': '189db77befff966d2132327626b4065a79a6ccc55cab4a2859609e888042e887',
        'string_romanian_vertical.uxc': 'b16171c7f3f6432dcc8798333b29f6d7ad5233dbc80b7595b85e58da4be95254',
        'string_russian_horizontal.uxc': '4cf13c8de2ad05cd88d510cdc3e9dd78b960848f89145b53ea785a66f43ddd64',
        'string_russian_vertical.uxc': 'e6a3f8f761918bfebc6785503a96363f444aaa3ef0c0e34c6eb0860f06bea9c4',
        'string_simplifiedchinese_horizontal.uxc': 'f136388b71e9431313002aee23f9c972b56e92602123b76b4786e0d3d872fb33',
        'string_simplifiedchinese_vertical.uxc': 'cefae46ff374f9a6423fa378cb60ffb1393d51987d77468a7a4ea65926924a44',
        'string_spanish_horizontal.uxc': 'e8d20c85d8970bc5e32409c3fa4b66fcd8989b4b748d5e733309062e36eb9da0',
        'string_spanish_vertical.uxc': '1277dfb02dfc064db7d02ef41cd8750e51bb7b2c05a6013627aaac82704fc4ee',
        'string_swedish_horizontal.uxc': '2bede831f0845be09cc011ac7d1df8600469d06951e5d86627d732e55a3ac90b',
        'string_swedish_vertical.uxc': '09d0210480ac13f33ce4683970867a66cb09969c33514ed8037ec5678f6078f0',
        'string_thai_horizontal.uxc': 'b33984b8909f029620ac7f3d8658d83c61afaa43c3f8eb8f07dd27d9ac0da5a1',
        'string_thai_vertical.uxc': '654bf7b2f995d9c85d377f52a2c3f8a6dd0605306d7f575412b1aa8977de068f',
        'string_traditionalchinese_horizontal.uxc': '8298eca861a6813a4d7d0aa9889f508112889050b8349e3b17433617a6558cae',
        'string_traditionalchinese_vertical.uxc': '69180fb77550e195609c52e1f252353176a00c990e6cf46e57330dd404196dbc',
        'string_turkish_horizontal.uxc': 'f2257aa92e207627d40e72d4879ac0d0e1049d92617018e02860b9152205391f',
        'string_turkish_vertical.uxc': '66881c6b09028410d73cc2e520c706a1abef7465336d5df72b02e9a5e06ee3d1',
        'string_ukrainian_horizontal.uxc': '9cf7c3cab3cda488eccb0790bde1d54e49a05635d23e3a29c53eed4ae8fd225b',
        'string_ukrainian_vertical.uxc': 'c5d1f98012860f91dc55112747213b8984d00094a2852f312e76ce8527fa0453',
        'string_vietnamese_horizontal.uxc': 'b89fbd01829f6f332099c45dcc30f32bb47940e2840433ce1f53061fa60d06ee',
        'string_vietnamese_vertical.uxc': 'cf5faaf551ca0820b9e17f8620f0cb0c7aad5874fbca2f6b38cd457085577c28',
    },
}


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


def resources(folder, name, filenames, digests):
    """{file name: bytes} of every name file in `filenames` for fixture build `name`, or None when the
    build has no name files. Each must have its SHA-256 in `digests` (RESOURCE_DIGESTS[name]): a folder
    lacking any file, holding one with another digest, or for a build with no recorded digests is
    refused, naming the files."""
    where = resources_folder(folder, name)
    if where is None:
        return None
    if digests is None:
        raise ValueError('%s has name files but no recorded digests: record them in '
                         'buildfixtures.RESOURCE_DIGESTS (report.json lists them)' % where)
    missing = [filename for filename in filenames if not (where / filename).is_file()]
    if missing:
        raise ValueError('%s lacks %d of its name files: %s' % (where, len(missing), ', '.join(missing[:3])))
    files = {filename: (where / filename).read_bytes() for filename in filenames}
    wrong = [filename for filename in filenames if sha(files[filename]) != digests.get(filename)]
    if wrong:
        raise ValueError('%s holds %d name files other than the recorded ones: %s' % (where, len(wrong), ', '.join(wrong[:3])))
    return files
