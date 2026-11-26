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


# --- архив ---------------------------------------------------------------------


def test_archive_feature_is_registered():
    assert "archive" in FEATURES
    # модуль «archive» виден в настройках, хотя команд у него нет
    assert "archive" in registry.modules()


@pytest.mark.parametrize("lang", ["ru", "en", "uk"])
def test_archive_locales_are_merged(lang):
    assert "archive.deleted_header" in LOCALES[lang]


def test_archive_logic_layers_do_not_import_aiogram():
    """Сервис, снимок, настройки и запросы не знают про aiogram (готовность к userbot)."""
    import ast
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent / "app/features/archive"
    for name in ("service", "snapshot", "prefs", "queries", "models"):
        tree = ast.parse((root / f"{name}.py").read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            names = []
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or ""]
            assert not [n for n in names if n.split(".")[0] == "aiogram"], name


def test_archive_router_has_all_handlers():
    from collections import Counter

    from app.features.archive.bot import router

    counts = Counter()
    for r in [router, *router.chain_tail]:
        for name, obs in r.observers.items():
            counts[name] += len(obs.handlers)
    assert counts["deleted_business_messages"] == 1
    assert counts["edited_business_message"] == 1
    assert counts["callback_query"] == 5  # + кнопки «архив заполнен»
