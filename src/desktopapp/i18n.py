"""Display-only localization. Worker actions, logs and saved camera data stay verbatim.

Adapted from the Korean localization on Gureum-Yeoreum-Tori/a7c2-fl23-research
(branch feat/korean-ui). Text without a catalog entry, including engine messages,
is shown unchanged.
"""
from .en import STRINGS

LANGUAGES = ('en', 'zh_CN')
_language = 'zh_CN'


def tr(source):
    return STRINGS.get(source, source) if _language == 'en' else source


def configure(language):
    global _language
    _language = language if language in LANGUAGES else 'en'
    return _language


_qt_translator = None  # kept referenced: Qt stops translating once the object is collected


def translate_qt(app):
    """Show Qt's own standard buttons (OK, Cancel, Close…) in the configured language. English
    needs no catalog; a missing catalog leaves them in English."""
    global _qt_translator
    from PySide6 import QtCore
    if _qt_translator is not None:
        app.removeTranslator(_qt_translator)
        _qt_translator = None
    if _language == 'en':
        return False
    translator = QtCore.QTranslator(app)
    if not translator.load('qtbase_' + _language, QtCore.QLibraryInfo.path(QtCore.QLibraryInfo.TranslationsPath)):
        return False
    app.installTranslator(translator)
    _qt_translator = translator
    return True
