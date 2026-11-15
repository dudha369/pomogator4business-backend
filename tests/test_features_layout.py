"""Раскладка по фичам: все фичи из FEATURES загружаются, команды и тексты на месте."""

import pytest

from app.features import FEATURES
from app.platform.i18n import LOCALES, t
from app.platform.telegram.registry import registry

# имя «модуля» в настройках пользователя не должно меняться при переносе файлов
EXPECTED_MODULES = {
    "mute": {"mute", "wmute"},
    "profile": {"profile"},
    "reminders": {"waiting"},
    "templates": {"tpl"},
    "ttt": {"ttt"},
    "hangman": {"hangman"},
    "city": {"city"},
    "guess": {"guess"},
}


@pytest.mark.parametrize("module,names", EXPECTED_MODULES.items())
def test_module_keeps_its_commands(module, names):
    assert names <= {c.name for c in registry.modules()[module]}


def test_features_list_is_explicit():
    assert set(FEATURES) >= {"games", "mute", "profile", "reminders", "templates"}


@pytest.mark.parametrize("lang", ["ru", "en", "uk"])
def test_feature_locales_are_merged(lang):
    for key in ("mute.disabled", "tpl.empty", "rem.header", "profile.usage_reply"):
        assert key in LOCALES[lang], (lang, key)
    assert t("mute.disabled", lang) != "mute.disabled"
