"""English for what the worker and the engine print and raise, at display time only (see i18n.py).

worker.log, process.log and the status files stay verbatim on disk, so diagnostics stay comparable
with upstream. The window passes what it shows from them (the log pane, the error banner, refusals,
an engine error in a dialog) through display(), which translates when the interface is English.

A message is found in the two catalogues, en.STRINGS (the interface) and en_engine.ENGINE (the worker
and the engine), keyed by the Chinese source:
- by its exact text, or one line of a longer entry;
- by its format: each %s, %d or %.Nf in a key matches the value the code filled in (the only
  specifiers the catalogues use).
A value is translated only when it is itself a message: an engine entry, or an interface sentence that
ends its clause (。；：！？); a supported build's key is shown as its label. Anything else is data and
stays as printed, so a catalogued format with an
uncatalogued Chinese value, such as a disk or look name, shows that value unchanged. The same rule reads
the value of a printed JSON result line and the message of an exception line. A value that is again a
format is read to DEEPEST levels; past that the rest of the line stays as printed. A line no entry
matches as a whole is shown unchanged too, full-width characters and all, never pieced together from
shorter entries; a line the code builds from several messages needs its own entry. A traceback's source
line keeps its code and shows a Chinese string literal in English, or as … when the literal is only part
of a message. Lines longer than LONGEST are not matched against formats, so a huge line costs no time.
"""
import json
import re

from . import i18n
from .en import STRINGS
from .en_engine import ENGINE

# CJK symbols and punctuation through the unified ideographs, the compatibility ideographs, and the half-
# and full-width forms; HAN is the ideographs alone. The tests and the coverage scan use these too.
CJK = re.compile('[\u3000-\u9fff\uf900-\ufaff\uff00-\uffef]')
HAN = re.compile('[\u3400-\u9fff\uf900-\ufaff]')
# The specifiers the catalogues use: %s, %d and %.Nf. The conversion is group 1.
SPECIFIER = re.compile(r'%(?:\.\d+)?([dfs])')
# What each conversion can have printed. Text is matched as briefly as the rest of the format allows.
VALUE = {'d': r'-?\d+', 'f': r'-?(?:\d+(?:\.\d*)?|\.\d+)|-?inf|nan', 's': '.*?'}
CLAUSE_END = ('\u3002', '\uff1b', '\uff1a', '\uff01', '\uff1f')  # an interface entry ending so is a sentence
LONGEST = 2000  # longer lines skip the formats: a format with two values can take quadratic time
DEEPEST = 8  # values are read as messages this many levels deep; deeper text stays as printed
# Interface text that display() never sees, so it is no entry here: the sound credit, which
# window.sound_page fills with named fields after tr().
NOT_DISPLAYED = frozenset({'“%(title)s”，作者 %(author)s，%(licence)s，来自 <a href="%(url)s">Freesound</a>。'})
EXCEPTION = re.compile(r'^([A-Za-z_][\w.]*): (.*)$', re.S)
JSON_STRING = re.compile(r'^((?:"(?:[^"\\]|\\.)*":\s*)?)"((?:[^"\\]|\\.)*)"(,?)$')
CODE_LITERAL = re.compile(r"""(?P<quote>['"])(?P<text>(?:(?!(?P=quote))[^\\\n]|\\.)*)(?P=quote)""")
# The Chinese label of each supported build, by key: refusals name a build by its key, the Connection page
# by its label. A copy of looktool.buildprofile.BUILDS (test_engine_text keeps the two equal), so display()
# never imports looktool, which a first source launch can import only after setup_runtime().
BUILD_LABELS = {'public-2.01': 'Sony 2.01（公开更新）',
                'body-2.01-20250923': 'Sony 2.01（机身版本，2025 年 9 月 23 日）'}


def specifiers(text):
    """The %-specifiers in `text`, in order, as written."""
    return [match.group() for match in SPECIFIER.finditer(text)]


def _pairs():
    """(Chinese, English, catalogue) for every entry display() may see, and for each line of a
    multi-line entry whose English has as many lines."""
    for table in (STRINGS, ENGINE):
        for source, english in table.items():
            if source in NOT_DISPLAYED:
                continue
            yield source, english, table
            if '\n' in source and source.count('\n') == english.count('\n'):
                for zh, en in zip(source.split('\n'), english.split('\n')):
                    if CJK.search(zh):
                        yield zh, en, table


def conflicts():
    """{Chinese: set of English} for each Chinese text given different English (spacing aside) by two
    entries, or by an entry and a line of a longer one. Each must read one way; the tests require none."""
    seen, found = {}, {}
    for zh, en, _ in _pairs():
        if zh in seen and seen[zh].strip() != en.strip():
            found.setdefault(zh, {seen[zh]}).add(en)
        seen.setdefault(zh, en)
    return found


def _is_format(source):
    return SPECIFIER.search(source) is not None


class Format:
    """A catalogue key with %-specifiers, as a pattern that recognises the formatted text."""

    def __init__(self, source, english, table):
        pieces = SPECIFIER.split(source)
        literal = pieces[0::2]
        regex = ''.join(re.escape(text) + '(' + VALUE[kind] + ')' for text, kind in zip(literal, pieces[1::2]))
        self.source, self.english, self.engine = source, english, table is ENGINE
        self.pattern = re.compile(regex + re.escape(literal[-1]), re.S)
        self.text = ''.join(literal)  # the key without its specifiers: how specific it is

    def translate(self, match, depth):
        """The English for the text `match` found, `depth` formats deep, each specifier filled in order
        with its value: in English when the value is itself a message (see _value), else as printed."""
        values = iter([_value(value, depth + 1) for value in match.groups()])
        return SPECIFIER.sub(lambda specifier: next(values), self.english)


def _catalogue():
    """(exact, formats, values): every exact text; every format holding at least two Chinese
    characters ('%s（%s）' alone would match too much), most specific first; and the exact texts a
    filled-in value may be read as (engine entries and interface sentences)."""
    exact, formats, values = {}, [], {}
    for zh, en, table in _pairs():
        if _is_format(zh):
            if len(HAN.findall(SPECIFIER.sub('', zh))) >= 2:
                formats.append(Format(zh, en, table))
            continue
        exact.setdefault(zh, en)  # one English per text: conflicts() is empty, the tests check it
        if table is ENGINE or zh.rstrip().endswith(CLAUSE_END):
            values.setdefault(zh, en)
    formats.sort(key=lambda found: -len(found.text))
    return exact, formats, values


EXACT, FORMATS, VALUES = _catalogue()
VALUE_FORMATS = [found for found in FORMATS if found.engine]


def lookup(text, exact=EXACT, formats=FORMATS, depth=0):
    """(key, English) of the catalogue entry whose whole message `text` is: an `exact` text, or the
    first of `formats` it fills in, its values read at `depth` (see _value); None when no entry matches
    `text` whole. The one lookup behind _message, source and _value."""
    if text in exact:
        return text, exact[text]
    if len(text) > LONGEST:
        return None
    for found in formats:
        match = found.pattern.fullmatch(text)
        if match:
            return found.source, found.translate(match, depth)
    return None


def _message(text):
    """English for one whole catalogued message, or None."""
    found = lookup(text)
    return found and found[1]


def source(text):
    """The catalogue key whose whole message `text` is: its exact text, or the format it fills in; None for
    text no entry matches whole. The window asks it what an error says, in either language."""
    found = lookup(text.strip())
    return found and found[0]


def _value(text, depth=0):
    """Text the engine filled into a message (a format's value, a JSON result's value, an exception's
    message), in English only when it is itself a message: an engine entry, or an interface sentence
    ending its clause, line by line if need be. Anything else, such as a disk or look name that happens to
    match a short interface label, is data and stays as printed; so does anything deeper than DEEPEST."""
    label = _build_label(text)
    if label is not None:
        return label
    if not CJK.search(text) or depth > DEEPEST:
        return text
    found = lookup(text, VALUES, VALUE_FORMATS, depth)
    if found is None and '\n' in text:
        return '\n'.join(_value(line, depth) for line in text.split('\n'))
    return text if found is None else found[1]


def _build_label(text):
    """The English label of the supported build whose key `text` is (refusals name builds by key, the
    Connection page by label), or None for any other text."""
    label = BUILD_LABELS.get(text)
    return None if label is None else STRINGS[label]


def _spacing(text):
    """(leading space, text, trailing space)."""
    core = text.strip()
    if not core:
        return text, '', ''
    start = text.index(core[0])
    return text[:start], core, text[start + len(core):]


def _json(text):
    """A "key": "value" line of a result the worker printed as JSON, its value read by the value rule."""
    match = JSON_STRING.match(text)
    if not match:
        return None
    try:
        value = json.loads('"' + match.group(2) + '"')
    except ValueError:
        return None
    return match.group(1) + json.dumps(_value(value), ensure_ascii=False) + match.group(3)


def _code(line):
    """A traceback's source line: each Chinese string literal in English, or … when it is only part
    of a message."""
    def literal(match):
        text = match.group('text')
        if not CJK.search(text):
            return match.group()
        english = _message(text)
        if english is None:
            return match.group('quote') + '…' + match.group('quote')
        return match.group('quote') + english.replace('\\', '\\\\').replace(match.group('quote'), '\\' + match.group('quote')) + match.group('quote')
    return CODE_LITERAL.sub(literal, line)


def translate_line(text):
    """One line of worker or engine output in English, so far as the catalogues know it."""
    if not CJK.search(text):
        return text
    if text in EXACT:
        return EXACT[text]
    lead, core, trail = _spacing(text)
    if len(lead) >= 4 and CODE_LITERAL.search(core) and not JSON_STRING.match(core):
        return lead + _code(core) + trail
    english = _message(core)
    if english is None:
        exception = EXCEPTION.match(core)
        if exception and not CJK.search(exception.group(1)):
            english = exception.group(1) + ': ' + _value(exception.group(2))
    if english is None:
        english = _json(core)
    # Nothing translated: the line is data (a name, a path) and is shown as printed.
    return text if english is None else lead + english + trail


def translate_text(text):
    """Worker or engine output of one or more lines in English: as one message when an entry with as many
    lines matches it whole and that leaves no Chinese, else line by line. The window reads worker.log in
    chunks of several lines, and a one-line format such as '一键安装：%s' would otherwise take the lines after
    its own as its value, so the first line would miss its exact entry."""
    if not CJK.search(text):
        return text
    if text in EXACT:  # an entry whose own spacing or line breaks are part of it
        return EXACT[text]
    lead, core, trail = _spacing(text)
    found = lookup(core)
    if found is not None and found[0].count('\n') == core.count('\n') and not HAN.search(found[1]):
        return lead + found[1] + trail
    return '\n'.join(translate_line(line) for line in text.split('\n'))


def display(text):
    """`text` as the window shows it: in English when the interface is English, else unchanged."""
    return translate_text(text) if i18n.language() == 'en' else text
