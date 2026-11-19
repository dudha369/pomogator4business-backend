import importlib
import pkgutil

import app.platform.locales as platform_locales_pkg
import commands.locales as commands_locales_pkg
from app.features import FEATURES, feature_module

DEFAULT_LOCALE = "ru"
LANGUAGE_NAMES = {"ru": "Русский", "en": "English", "uk": "Українська"}
_LANG_ATTR = {"ru": "RU", "en": "EN", "uk": "UK"}


def _merge_all():
    merged = {"ru": {}, "en": {}, "uk": {}}
    packages = [platform_locales_pkg, commands_locales_pkg]
    packages += [m for m in (feature_module(n, "locales") for n in FEATURES) if m]
    for package in packages:
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
