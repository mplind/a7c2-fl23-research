"""English for what the worker and the engine print and raise, at display time only (see i18n.py).

worker.log, process.log and the status files stay verbatim on disk, so diagnostics stay comparable
with upstream. The window passes what it shows from them (the log pane, the error banner, refusals,
an engine error in a dialog) through display(), which translates when the interface is English.

A message is found in the two catalogues, en.STRINGS (the interface) and en_engine.ENGINE (the worker
and the engine), keyed by the Chinese source:
- by its exact text;
- by its format: each %s, %d … in a key matches the value the code filled in, and a value that is
  itself a catalogued message is translated in turn;
- line by line, when a message runs over several lines;
- as the parts of a line the code built from several messages (a known message followed by another,
  or by English), longest part first.
A traceback's source line keeps its code but shows a Chinese string literal in English, or as …
when the literal is only part of a message. Text with no entry, such as a file name read from the
camera, is shown unchanged.
"""
import json
import re

from . import i18n
from .en import STRINGS
from .en_engine import ENGINE

CJK = re.compile('[\u3000-\u9fff\uf900-\ufaff\uff00-\uffef]')
HAN = re.compile('[\u3400-\u9fff\uf900-\ufaff]')
SPECIFIER = re.compile(r'%(?:\(([^)]+)\))?[#0\- +]*\d*(?:\.\d+)?([diouxXeEfFgGcrsa%])')
# What each conversion can have printed. Text is matched as briefly as the rest of the format allows.
VALUE = {**dict.fromkeys('diu', r'-?\d+'), **dict.fromkeys('fFeEgG', r'-?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?|-?inf|nan'),
         **dict.fromkeys('xXo', r'[0-9a-fA-F]+')}
# Full-width punctuation left between translated or ASCII text, once no Chinese word remains.
PUNCTUATION = {'，': ', ', '。': '. ', '；': '; ', '：': ': ', '（': ' (', '）': ') ', '、': ', ', '！': '! ', '？': '? ',
               '「': '"', '」': '"', '『': '"', '』': '"', '《': '"', '》': '"', '【': '[', '】': ']', '／': '/',
               '～': '~', '－': '-', '＋': '+', '＝': '=', '\u3000': ' '}
LINE_START = re.compile(r'^(\s*)(.*?)(\s*)$', re.S)
EXCEPTION = re.compile(r'^([A-Za-z_][\w.]*): (.*)$', re.S)
JSON_STRING = re.compile(r'^((?:"(?:[^"\\]|\\.)*":\s*)?)"((?:[^"\\]|\\.)*)"(,?)$')
CODE_LITERAL = re.compile(r"""(?P<quote>['"])(?P<text>(?:(?!(?P=quote))[^\\\n]|\\.)*)(?P=quote)""")


class Format:
    """A catalogue key with %-specifiers, as a pattern that recognises the formatted text."""

    def __init__(self, source, english):
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
        self.source, self.english, self.names = source, english, names
        self.pattern = re.compile(regex, re.S)
        self.text = ''.join(literal)      # the key without its specifiers: how specific it is
        self.closed = bool(literal[-1])   # ends in fixed text, so it can be found inside a line

    def fill(self, values):
        """The English with each specifier replaced by the matching (translated) value, in order or by name."""
        named = dict(zip(self.names, values))
        ordered = iter(values)

        def value(match):
            if match.group(2) == '%':
                return '%'
            return named[match.group(1)] if match.group(1) else next(ordered)
        return SPECIFIER.sub(value, self.english)


def _catalogue():
    """(exact, formats): every entry, plus each line of a multi-line entry whose English has as many lines."""
    exact, formats = {}, []
    for source, english in list(STRINGS.items()) + list(ENGINE.items()):
        pairs = [(source, english)]
        if '\n' in source and source.count('\n') == english.count('\n'):
            pairs += [line for line in zip(source.split('\n'), english.split('\n')) if CJK.search(line[0])]
        for zh, en in pairs:
            if any(match.group(2) != '%' for match in SPECIFIER.finditer(zh)):
                if len(HAN.findall(SPECIFIER.sub('', zh))) >= 2:  # '%s（%s）' alone would match too much
                    formats.append(Format(zh, en))
            else:
                exact.setdefault(zh, en)
    formats.sort(key=lambda found: -len(found.text))
    return exact, formats


EXACT, FORMATS = _catalogue()


def _index():
    """The parts a line can be built from, listed under the character they start with: exact entries
    holding at least two Chinese characters, longest first, and single-line formats. Formats that
    start with a value can start anywhere, so they are listed under ''."""
    exact, formats = {}, {}
    for source in EXACT:
        if len(HAN.findall(source)) >= 2 and '\n' not in source:
            exact.setdefault(source[0], []).append(source)
    for parts in exact.values():
        parts.sort(key=len, reverse=True)
    for found in FORMATS:
        if '\n' not in found.source:
            first = SPECIFIER.match(found.source)
            formats.setdefault('' if first and first.group(2) != '%' else found.source[0], []).append(found)
    return exact, formats


EXACT_PARTS, FORMAT_PARTS = _index()


def _message(text):
    """English for one whole catalogued message, or None."""
    if text in EXACT:
        return EXACT[text]
    for found in FORMATS:
        match = found.pattern.fullmatch(text)
        if match:
            return found.fill([translate_text(value) for value in match.groups()])
    return None


def _space(done, english):
    """English parts join with a space after a sentence or clause ends."""
    if done and done[-1] in '.:;,!?)' and english[:1].isalnum():
        return ' ' + english
    return english


def _parts(text):
    """The line read as consecutive catalogued messages, longest first at each place, with other
    characters kept as they are; None unless that leaves no Chinese word, so a line is never shown
    half translated."""
    out, at = '', 0
    while at < len(text):
        best = None
        for source in EXACT_PARTS.get(text[at], ()):
            if text.startswith(source, at):
                best = (len(source), EXACT[source])
                break
        for found in FORMAT_PARTS.get(text[at], []) + FORMAT_PARTS.get('', []):
            match = (found.pattern.match(text, at) if found.closed else found.pattern.fullmatch(text, at))
            if match and match.end() > at and (best is None or match.end() - at > best[0]):
                best = (match.end() - at, found.fill([translate_text(value) for value in match.groups()]))
        if best and HAN.search(text, at, at + best[0]):
            out += _space(out, best[1])
            at += best[0]
        else:
            out += text[at]
            at += 1
    return None if HAN.search(out) else out


def _json(text):
    """A "key": "value" line of a result the worker printed as JSON, with the value in English."""
    match = JSON_STRING.match(text)
    if not match:
        return None
    try:
        value = json.loads('"' + match.group(2) + '"')
    except ValueError:
        return None
    return match.group(1) + json.dumps(translate_text(value), ensure_ascii=False) + match.group(3)


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
    lead, core, trail = LINE_START.match(text).groups()
    if len(lead) >= 4 and CODE_LITERAL.search(core) and not JSON_STRING.match(core):
        return lead + _punctuation(_code(core)) + trail
    english = _message(core)
    if english is None:
        exception = EXCEPTION.match(core)
        if exception and not CJK.search(exception.group(1)):
            english = exception.group(1) + ': ' + translate_text(exception.group(2))
    if english is None:
        english = _json(core)
    if english is None:
        english = _parts(core)
    return lead + _punctuation(core if english is None else english) + trail


def translate_text(text):
    """Worker or engine output of one or more lines in English: as one message if it is one, else
    line by line."""
    if not CJK.search(text):
        return text
    if text in EXACT:  # an entry whose own spacing or line breaks are part of it
        return EXACT[text]
    lead, core, trail = LINE_START.match(text).groups()
    english = _message(core)
    if english is not None:
        return lead + english + trail
    return '\n'.join(translate_line(line) for line in text.split('\n'))


def display(text):
    """`text` as the window shows it: in English when the interface is English, else unchanged."""
    return translate_text(text) if i18n.language() == 'en' else text
