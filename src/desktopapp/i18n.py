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
