"""Every Chinese message the app can show has an English translation (Task 8b, R38).

The scan reads the in-scope source with ast. Each string literal holding a CJK character, outside
docstrings, belongs to a message: the literal itself, or the string the code builds around it (a %
format, a + concatenation, an f-string, str.format, or a print() of several arguments). A literal that
picks one of several values (x if c else y, x or y) gives one message per value, and the parts the code
fills in at run time are %s. Every message so formed must be catalogued:

- a literal passed straight to tr() needs its entry in desktopapp.en.STRINGS (tr looks there only), and
  so does a module constant passed to tr() or translate(), such as DRIVER_HINT or the Terminal PROMPT;
- any other message needs an entry in en.STRINGS or desktopapp.en_engine.ENGINE, which
  desktopapp.engine_text uses at display time, by exact text or by format.

A literal that is no message (a value the code only compares, a name shown in its own language) sits
in ALLOWLIST with its reason; the allowlist is checked against the source, so it cannot rot.
"""
import ast
import itertools
from pathlib import Path
import re

from desktopapp.en import STRINGS
from desktopapp.en_engine import ENGINE
from desktopapp.engine_text import CJK

ROOT = Path(__file__).resolve().parents[2]
TRANSLATORS = {'tr', 'translate'}  # the two functions that look a text up in STRINGS
# Everything a user sees during a camera job: the app, the worker and the engine code it runs.
TREES = ('src/desktopapp', 'src/looks/looktool', 'src/camera_runtime', 'src/shutter_sound', 'src/vertical')
# The desktop app never runs the standalone FL23 tool's window (src/fl23 is outside TREES as well); the
# two catalogues hold the Chinese as keys; the translator holds only character classes and the
# full-width punctuation it maps.
SKIPPED = {'src/camera_runtime/app.py', 'src/camera_runtime/gui.py', 'src/desktopapp/en.py',
           'src/desktopapp/en_engine.py', 'src/desktopapp/engine_text.py'}

# (file, literal): why the literal is not a message that needs English.
ALLOWLIST = {
    ('src/desktopapp/window.py', '.!?\u3002\uff01\uff1f'):
        'sentence-end marks the stopped banner compares, so it never shows two full stops; never shown itself',
    ('src/desktopapp/allinone.py', '冷启动'):
        'only compared: a verify error mentioning a cold restart means the one-click job waits for one; the '
        'error itself is catalogued',
}


def sources():
    for tree in TREES:
        for path in sorted((ROOT / tree).rglob('*.py')):
            relative = path.relative_to(ROOT)
            if (relative.as_posix() in SKIPPED or {'vendor', 'tests', '__pycache__'} & set(relative.parts)
                    or path.name.startswith('test_')):
                continue
            yield relative.as_posix(), path


def called(node):
    """The plain name a call is made through (tr, print), or None."""
    return node.func.id if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) else None


def printed_with_others(node, parent):
    return (called(parent) == 'print' and len(parent.args) > 1 and node in parent.args
            and not any(keyword.arg == 'sep' for keyword in parent.keywords))


def message_root(node, parent_of):
    """The outermost expression that builds one string out of `node`."""
    while True:
        parent = parent_of.get(node)
        if (isinstance(parent, ast.IfExp) and node is not parent.test) or isinstance(parent, (ast.BoolOp, ast.JoinedStr)):
            node = parent
        elif isinstance(parent, ast.BinOp) and (isinstance(parent.op, ast.Add)
                                                or (isinstance(parent.op, ast.Mod) and node is parent.left)):
            node = parent
        elif (isinstance(parent, ast.Attribute) and parent.attr == 'format'
              and isinstance(parent_of.get(parent), ast.Call) and parent_of[parent].func is parent):
            node = parent_of[parent]
        elif printed_with_others(node, parent):
            node = parent
        else:
            return node


def forms(node):
    """Every text `node` can produce, with %s where the code fills in a value at run time."""
    if isinstance(node, ast.Constant):
        return {node.value} if isinstance(node.value, str) else {'%s'}
    if isinstance(node, ast.IfExp):
        return forms(node.body) | forms(node.orelse)
    if isinstance(node, ast.BoolOp):
        return set().union(*(forms(value) for value in node.values))
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        return {left + right for left in forms(node.left) for right in forms(node.right)}
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Mod):
        return forms(node.left)  # the template; its own %-specifiers are the values
    if isinstance(node, ast.JoinedStr):
        return {''.join(part.value if isinstance(part, ast.Constant) else '%s' for part in node.values)}
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == 'format':
        return {re.sub(r'\{[^{}]*\}', '%s', text) for text in forms(node.func.value)}
    if called(node) == 'print':
        return {' '.join(parts) for parts in itertools.product(*(sorted(forms(arg)) for arg in node.args))}
    return {'%s'}


def statements_only(tree):
    """Strings standing alone as statements: docstrings and comment blocks, never shown."""
    return {id(node.value) for node in ast.walk(tree)
            if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str)}


def literals(files=None):
    """(file, line, literal, kind, forms) for every CJK literal in `files` ((name, path) pairs; the
    in-scope source by default); kind is 'tr' for a literal passed straight to tr(), else 'message'."""
    for relative, path in (sources() if files is None else files):
        tree = ast.parse(path.read_text(encoding='utf-8'))
        parent_of = {child: node for node in ast.walk(tree) for child in ast.iter_child_nodes(node)}
        silent = statements_only(tree)
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Constant) and isinstance(node.value, str) and CJK.search(node.value)):
                continue
            if id(node) in silent:
                continue
            parent = parent_of.get(node)
            if called(parent) in TRANSLATORS and parent.args and parent.args[0] is node:
                yield relative, node.lineno, node.value, 'tr', {node.value}
            else:
                text = {form for form in forms(message_root(node, parent_of)) if CJK.search(form)}
                yield relative, node.lineno, node.value, 'message', text


def texts_of(node):
    """The texts a constant holds: a string, or a tuple or list of strings; None for anything else."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return [node.value]
    if isinstance(node, (ast.Tuple, ast.List)) and all(texts_of(item) for item in node.elts):
        return [text for item in node.elts for text in texts_of(item)]
    return None


def constants(path):
    """{name: texts} for the module-level string constants of the source file at `path`."""
    tree = ast.parse(path.read_text(encoding='utf-8'))
    found = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            texts = texts_of(node.value)
            if texts is not None:
                found[node.targets[0].id] = texts
    return found


def module_path(path, level, module):
    """The source file an import names: relative to `path`'s package, or desktopapp / looktool."""
    if level:
        base = path.parent
        for _ in range(level - 1):
            base = base.parent
    else:
        top = (module or '').split('.')[0]
        base = {'desktopapp': ROOT / 'src', 'looktool': ROOT / 'src/looks'}.get(top)
        if base is None:
            return None
    target = base.joinpath(*module.split('.')) if module else base
    for candidate in (target.with_suffix('.py'), target / '__init__.py'):
        if candidate.is_file():
            return candidate
    return None


def translated_constants(files=None):
    """(file, line, text) for each module constant passed to tr() or translate(): a name defined in the
    module or imported from another, a module's attribute (presets.SUMMARY), or a name a comprehension
    takes from such a constant (the Terminal PROMPT lines)."""
    for relative, path in (sources() if files is None else files):
        tree = ast.parse(path.read_text(encoding='utf-8'))
        own, names, modules, loops = constants(path), {}, {}, {}
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                for alias in node.names:
                    source = module_path(path, node.level, node.module)
                    if source is not None and alias.name in constants(source):
                        names[alias.asname or alias.name] = constants(source)[alias.name]
                    submodule = module_path(path, node.level, ((node.module + '.') if node.module else '') + alias.name)
                    if submodule is not None:
                        modules[alias.asname or alias.name] = submodule
            if isinstance(node, ast.comprehension) and isinstance(node.target, ast.Name) and isinstance(node.iter, ast.Name):
                loops[node.target.id] = node.iter.id
        for node in ast.walk(tree):
            if not (called(node) in TRANSLATORS and node.args):
                continue
            argument, texts = node.args[0], None
            if isinstance(argument, ast.Name):
                name = loops.get(argument.id, argument.id)
                texts = own.get(name) or names.get(name)
            elif isinstance(argument, ast.Attribute) and isinstance(argument.value, ast.Name) \
                    and argument.value.id in modules:
                texts = constants(modules[argument.value.id]).get(argument.attr)
            for text in texts or ():
                if CJK.search(text):
                    yield relative, node.lineno, text


def uncovered(files=None):
    known = set(STRINGS) | set(ENGINE)
    missing = []
    for relative, line, value, kind, texts in literals(files):
        if (relative, value) in ALLOWLIST:
            continue
        table = STRINGS if kind == 'tr' else known
        missing += ['%s:%d %r' % (relative, line, text) for text in sorted(texts) if text not in table]
    missing += ['%s:%d %r (passed to tr or translate)' % (relative, line, text)
                for relative, line, text in translated_constants(files) if text not in STRINGS]
    return missing


def test_the_scan_finds_the_known_messages():
    # Shapes the scan must see through: a %-format joined to a constant (macos_host), an f-string
    # (transport), a branch inside a concatenation (usb_drivers), several print() arguments, and a
    # literal passed to tr().
    found = {(relative, text) for relative, _, _, _, texts in literals() for text in texts}
    assert ('src/camera_runtime/macos_host.py', '服务模式已退出，等待普通 USB 连接（最多 %d 秒）。%s') in found
    assert ('src/camera_runtime/macos_host.py', '正在卸载相机磁盘（不拔线）：%s') in found
    assert ('src/camera_runtime/transport.py', 'Jiritsu 狀態 %s') in found
    assert ('src/desktopapp/platforms/usb_drivers.py',
            '未找到相机的海量存储身份 054C:0E8A，请在相机选择“海量存储”后重新连接。当前检测：%s。完整设备／接口信息已保存，不会为未知 PID 自动更换驱动。') in found
    assert ('src/desktopapp/window.py', '就绪。选择左侧功能；启动软件不会访问相机。') in found
    # A message kept as a module constant and filled in with %, as presets keeps its two refusals.
    from desktopapp import presets
    assert {('src/desktopapp/presets.py', presets.MISSING), ('src/desktopapp/presets.py', presets.INVALID)} <= found


def test_every_message_has_english():
    assert uncovered() == []


def test_the_scan_resolves_constants_passed_to_tr_and_translate():
    found = {(relative, text) for relative, _, text in translated_constants()}
    from desktopapp.platforms.macos_authorization import FINISHED, PROMPT
    from desktopapp.window import DRIVER_HINT
    from desktopapp import connectionguide, presets
    assert {('src/desktopapp/window.py', DRIVER_HINT), ('src/desktopapp/presets.py', presets.SUMMARY),
            ('src/desktopapp/presets.py', presets.IN_ORDER), ('src/desktopapp/presets.py', presets.ONE_DARK),
            ('src/desktopapp/presets.py', presets.SEVERAL_DARK), ('src/desktopapp/window.py', connectionguide.TITLE),
            ('src/desktopapp/platforms/macos_authorization.py', FINISHED)} <= found
    assert {('src/desktopapp/platforms/macos_authorization.py', line) for line in PROMPT} <= found


NEGATIVE_CONTROL = """from .i18n import tr
NEW_LABEL = '普通 USB 连接已恢复。'


def stopped(x):
    print('新消息')
    if x:
        raise ValueError(f'新的错误 {x}')
    print(tr(NEW_LABEL))
    return '新的格式 %s' % x
"""


def test_the_scan_reports_messages_it_has_never_seen(tmp_path):
    # A standing negative control: new messages in each shape are reported, so a scan that silently
    # stopped seeing them would fail here. The constant is an engine entry, but tr() needs it in STRINGS.
    package = tmp_path / 'desktopapp'
    package.mkdir()
    source = package / 'newmodule.py'
    source.write_text(NEGATIVE_CONTROL, encoding='utf-8')
    files = [('newmodule.py', source)]
    assert sorted(text for *_, texts in literals(files) for text in texts) == [
        '新消息', '新的格式 %s', '新的错误 %s', '普通 USB 连接已恢复。']
    reported = uncovered(files)
    for text in ('新消息', '新的错误 %s', '新的格式 %s'):
        assert any(repr(text) in line for line in reported), text
    assert any('普通 USB 连接已恢复。' in line and 'tr or translate' in line for line in reported)


def test_every_skipped_file_exists():
    # A renamed or deleted file would leave its entry here, quietly skipping nothing.
    assert sorted(name for name in SKIPPED if not (ROOT / name).is_file()) == []


def test_every_allowlisted_literal_is_still_in_the_source():
    found = {(relative, value) for relative, _, value, _, _ in literals()}
    assert sorted(set(ALLOWLIST) - found) == []


def test_no_allowlisted_literal_is_catalogued_as_well():
    # A literal with an entry needs no exception; drop it from the allowlist instead.
    assert sorted(value for _, value in ALLOWLIST if value in STRINGS or value in ENGINE) == []


def test_every_allowlist_entry_gives_its_reason():
    assert all(len(reason) > 20 for reason in ALLOWLIST.values())
