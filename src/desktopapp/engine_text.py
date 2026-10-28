"""English for what the worker and the engine print and raise, at display time only (see i18n.py).

worker.log, process.log and the status files stay verbatim on disk, so diagnostics stay comparable
with upstream. The window passes what it shows from them (the log pane, the error banner, refusals,
an engine error in a dialog) through display(), which translates when the interface is English.

A message is found in the two catalogues, en.STRINGS (the interface) and en_engine.ENGINE (the worker
and the engine), keyed by the Chinese source:
- by its exact text, or one line of a longer entry;
- by its format: each %s, %d … in a key matches the value the code filled in.
A value is translated only when it is itself a message: an engine entry, or an interface sentence that
ends its clause (。；：！？). Anything else is data and stays as printed, so a catalogued format with an
uncatalogued Chinese value, such as a disk or look name, shows that value unchanged. The same rule reads
the value of a printed JSON result line and the message of an exception line. A value that is again a
format is read to DEEPEST levels; past that the rest of the line stays as printed. A line no entry
matches as a whole is shown unchanged too, never pieced together from shorter entries; a line the code
builds from several messages needs its own entry. A traceback's source line keeps its code and shows a
Chinese string literal in English, or as … when the literal is only part of a message. Lines longer than
LONGEST are not matched against formats, so a huge line costs no time.
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
SPECIFIER = re.compile(r'%(?:\(([^)]+)\))?[#0\- +]*\d*(?:\.\d+)?([diouxXeEfFgGcrsa%])')
# What each conversion can have printed. Text is matched as briefly as the rest of the format allows.
VALUE = {**dict.fromkeys('diu', r'-?\d+'), **dict.fromkeys('fFeEgG', r'-?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?|-?inf|nan'),
         **dict.fromkeys('xXo', r'[0-9a-fA-F]+')}
CLAUSE_END = ('\u3002', '\uff1b', '\uff1a', '\uff01', '\uff1f')  # an interface entry ending so is a sentence
LONGEST = 2000  # longer lines skip the formats: a format with two values can take quadratic time
DEEPEST = 8  # values are read as messages this many levels deep; deeper text stays as printed
# Full-width punctuation left between translated or ASCII text, once no Chinese word remains.
PUNCTUATION = {'，': ', ', '。': '. ', '；': '; ', '：': ': ', '（': ' (', '）': ') ', '、': ', ', '！': '! ', '？': '? ',
               '「': '"', '」': '"', '『': '"', '』': '"', '《': '"', '》': '"', '【': '[', '】': ']', '／': '/',
               '～': '~', '－': '-', '＋': '+', '＝': '=', '\u3000': ' '}
EXCEPTION = re.compile(r'^([A-Za-z_][\w.]*): (.*)$', re.S)
JSON_STRING = re.compile(r'^((?:"(?:[^"\\]|\\.)*":\s*)?)"((?:[^"\\]|\\.)*)"(,?)$')
CODE_LITERAL = re.compile(r"""(?P<quote>['"])(?P<text>(?:(?!(?P=quote))[^\\\n]|\\.)*)(?P=quote)""")


def specifiers(text):
    """The %-specifiers in `text`, in order, as written."""
    return [match.group() for match in SPECIFIER.finditer(text)]


def _pairs():
    """(Chinese, English, catalogue) for every entry, and for each line of a multi-line entry whose
    English has as many lines."""
    for table in (STRINGS, ENGINE):
        for source, english in table.items():
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
    return any(match.group(2) != '%' for match in SPECIFIER.finditer(source))


class Format:
    """A catalogue key with %-specifiers, as a pattern that recognises the formatted text."""

    def __init__(self, source, english, table):
        pieces, names, regex = SPECIFIER.split(source), [], ''
        literal = pieces[0::3]
        for index, (name, kind) in enumerate(zip(pieces[1::3], pieces[2::3])):
            regex += re.escape(literal[index])
            if kind == '%':
                regex += '%'
            else:
                names.append(name)
                regex += '(' + VALUE.get(kind, '.*?') + ')'
        regex += re.escape(literal[-1])
        self.source, self.english, self.names, self.engine = source, english, names, table is ENGINE
        self.pattern = re.compile(regex, re.S)
        self.text = ''.join(literal)  # the key without its specifiers: how specific it is

    def translate(self, match, depth):
        """The English for the text `match` found, `depth` formats deep, each specifier filled with its
        value: in English when the value is itself a message (see _value), else as printed. Named
        specifiers fill by name."""
        values = [_value(value, depth + 1) for value in match.groups()]
        named, ordered = dict(zip(self.names, values)), iter(values)

        def fill(specifier):
            if specifier.group(2) == '%':
                return '%'
            return named[specifier.group(1)] if specifier.group(1) else next(ordered)
        return SPECIFIER.sub(fill, self.english)


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


def _format(text, formats, depth=0):
    """English for `text` by the first of `formats` it fully matches, or None."""
    if len(text) > LONGEST:
        return None
    for found in formats:
        match = found.pattern.fullmatch(text)
        if match:
            return found.translate(match, depth)
    return None


def _message(text):
    """English for one whole catalogued message, or None."""
    return EXACT[text] if text in EXACT else _format(text, FORMATS)


def source(text):
    """The catalogue key whose whole message `text` is: its exact text, or the format it fills in; None for
    text no entry matches whole. The window asks it what an error says, in either language."""
    core = text.strip()
    if core in EXACT:
        return core
    if len(core) > LONGEST:
        return None
    for found in FORMATS:
        if found.pattern.fullmatch(core):
            return found.source
    return None


def _value(text, depth=0):
    """Text the engine filled into a message (a format's value, a JSON result's value, an exception's
    message), in English only when it is itself a message: an engine entry, or an interface sentence
    ending its clause, line by line if need be. Anything else, such as a disk or look name that happens to
    match a short interface label, is data and stays as printed; so does anything deeper than DEEPEST."""
    if not CJK.search(text) or depth > DEEPEST:
        return text
    if text in VALUES:
        return VALUES[text]
    english = _format(text, VALUE_FORMATS, depth)
    if english is None and '\n' in text:
        return '\n'.join(_value(line, depth) for line in text.split('\n'))
    return text if english is None else english


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


def _punctuation(text):
    if HAN.search(text) or not CJK.search(text):
        return text
    for mark, plain in PUNCTUATION.items():
        text = text.replace(mark, plain)
    return re.sub(r' +([,.;:)!?])', r'\1', re.sub(r'  +', ' ', text)).strip()


def translate_line(text):
    """One line of worker or engine output in English, so far as the catalogues know it."""
    if not CJK.search(text):
        return text
    if text in EXACT:
        return EXACT[text]
    lead, core, trail = _spacing(text)
    if len(lead) >= 4 and CODE_LITERAL.search(core) and not JSON_STRING.match(core):
        return lead + _punctuation(_code(core)) + trail
    english = _message(core)
    if english is None:
        exception = EXCEPTION.match(core)
        if exception and not CJK.search(exception.group(1)):
            english = exception.group(1) + ': ' + _value(exception.group(2))
    if english is None:
        english = _json(core)
    return lead + _punctuation(core if english is None else english) + trail


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
    entry = source(core)
    if entry is not None and entry.count('\n') == core.count('\n'):
        english = _message(core)
        if english is not None and not HAN.search(english):
            return lead + english + trail
    return '\n'.join(translate_line(line) for line in text.split('\n'))


def display(text):
    """`text` as the window shows it: in English when the interface is English, else unchanged."""
    return translate_text(text) if i18n.language() == 'en' else text
