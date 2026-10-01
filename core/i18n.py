import importlib
import pkgutil

import core.locales.themes as themes_pkg
import modules.locales as modules_locales_pkg

DEFAULT_LOCALE = "ru"
LANGUAGE_NAMES = {"ru": "Русский", "en": "English", "uk": "Українська"}
_LANG_ATTR = {"ru": "RU", "en": "EN", "uk": "UK"}


def _merge_all():
    merged = {"ru": {}, "en": {}, "uk": {}}
    for package in (themes_pkg, modules_locales_pkg):
        for info in pkgutil.iter_modules(package.__path__):
            mod = importlib.import_module(f"{package.__name__}.{info.name}")
            for locale, attr in _LANG_ATTR.items():
                merged[locale].update(getattr(mod, attr, {}))
    return merged


LOCALES = _merge_all()


def t(key, locale=DEFAULT_LOCALE, **kwargs):
    strings = LOCALES.get(locale, LOCALES[DEFAULT_LOCALE])
    template = strings.get(key) or LOCALES[DEFAULT_LOCALE].get(key) or key

    if not kwargs:
        return template

    try:
        return template.format(**kwargs)
    except (KeyError, IndexError):
        return template
