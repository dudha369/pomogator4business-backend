"""Арх.6: `core/`, `handlers/`, `api/`, `mirror/`, `emoji_clock/` переехали в `app/`.

Тесты держат раскладку: старых пакетов нет, никто на них не ссылается, у каждой
фичи модели зарегистрированы, слои без aiogram чисты, шрифты находятся."""

import ast
import importlib
import pkgutil
from pathlib import Path

import pytest

from app.features import FEATURES, feature_module
from config import ROOT_DIR, TORTOISE_ORM

LEGACY_PACKAGES = ("core", "handlers", "api", "mirror", "emoji_clock")
KERNEL_MODELS = {
    "__init__",
    "command_alias",
    "connection",
    "module_settings",
    "user_locale",
}
SOURCE_DIRS = ("app", "commands", "db", "scripts", "tests")


def _py_files():
    for name in SOURCE_DIRS:
        yield from (ROOT_DIR / name).rglob("*.py")
    for name in ("config.py", "bot_instance.py", "__main__.py"):
        yield ROOT_DIR / name


def _imports(path: Path) -> set[str]:
    out = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            out.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            out.add(node.module)
            out.update(f"{node.module}.{a.name}" for a in node.names)
    return out


@pytest.mark.parametrize("package", LEGACY_PACKAGES)
def test_legacy_package_is_gone(package):
    assert not list((ROOT_DIR / package).rglob("*.py")), package


def test_nobody_imports_legacy_modules():
    legacy = set(LEGACY_PACKAGES)
    for path in _py_files():
        for module in _imports(path):
            head = module.split(".")[0]
            assert head not in legacy, (str(path.relative_to(ROOT_DIR)), module)
            parts = module.split(".")
            # `from db.models import Connection` даёт имя класса, а не подмодуль
            if module.startswith("db.models.") and not parts[2][0].isupper():
                assert parts[2] in KERNEL_MODELS, (path.name, module)


def test_db_models_keep_only_the_shared_kernel():
    names = {p.stem for p in (ROOT_DIR / "db/models").glob("*.py")}
    assert names == KERNEL_MODELS


def test_every_module_imports_cleanly():
    for root in ("app", "commands"):
        package = importlib.import_module(root)
        for info in pkgutil.walk_packages(package.__path__, f"{root}."):
            importlib.import_module(info.name)


def test_feature_models_are_registered_in_tortoise():
    registered = set(TORTOISE_ORM["apps"]["models"]["models"])
    for feature in FEATURES:
        if (ROOT_DIR / "app/features" / feature / "models.py").exists():
            assert f"app.features.{feature}.models" in registered, feature
    for module in registered - {"aerich.models"}:
        importlib.import_module(module)


def test_every_feature_part_is_importable():
    for feature in FEATURES:
        assert importlib.import_module(f"app.features.{feature}")
        for part in ("bot", "api", "locales"):
            feature_module(
                feature, part
            )  # необязательные части: нет — None, есть — импортируется


def test_new_features_are_registered():
    assert {
        "ai",
        "autoresponder",
        "chats",
        "connection",
        "echo",
        "emoji_clock",
        "miniapp",
        "mirror",
        "scheduled",
        "settings",
        "stats",
        "story",
        "voice_effects",
    } <= set(FEATURES)


NO_AIOGRAM = (
    "ai/service.py",
    "autoresponder/service.py",
    "stats/service.py",
    "story/service.py",
    "scheduled/service.py",
    "connection/service.py",
)


@pytest.mark.parametrize("rel", NO_AIOGRAM)
def test_logic_layers_do_not_import_aiogram(rel):
    mods = _imports(ROOT_DIR / "app/features" / rel)
    assert not [m for m in mods if m.split(".")[0] == "aiogram"], rel


def test_models_and_queries_do_not_import_aiogram():
    for path in (ROOT_DIR / "app/features").glob("*/models.py"):
        assert not [m for m in _imports(path) if m.split(".")[0] == "aiogram"], path
    for path in (ROOT_DIR / "app/features").glob("*/queries.py"):
        assert not [m for m in _imports(path) if m.split(".")[0] == "aiogram"], path


def test_models_do_not_import_queries():
    for path in (ROOT_DIR / "app/features").glob("*/models.py"):
        assert not [m for m in _imports(path) if m.endswith(".queries")], path


def test_clock_fonts_are_found_after_move():
    from app.features.emoji_clock.render import text
    from app.features.emoji_clock.sync import preview

    for root in (text._ROOT, preview._ROOT):
        assert (Path(root) / "assets/fonts/Baloo2-Bold.ttf").exists()


def test_split_modules_keep_their_public_names():
    """Имена, которые раньше жили в одном файле и теперь разнесены по слоям."""
    from app.features.ai import bot as ai_bot
    from app.features.ai import service as ai_service
    from app.features.autoresponder import bot as ar_bot
    from app.features.autoresponder import service as ar_service
    from app.features.story import bot as story_bot
    from app.features.story import service as story_service

    for mod, names in (
        (ai_service, ("complete", "generate_reply", "is_configured", "build_messages")),
        (
            ai_bot,
            (
                "draft_keyboard",
                "notify_draft",
                "deliver_reply",
                "on_draft_button",
                "router",
            ),
        ),
        (
            ar_service,
            (
                "AutoReply",
                "build_candidates",
                "in_away_window",
                "pick_keyword",
                "render",
                "NO_SETTINGS",
            ),
        ),
        (ar_bot, ("handle_incoming", "autoresponder_step")),
        (story_service, ("split_image", "GRID")),
        (story_bot, ("cmd_story",)),
    ):
        for name in names:
            assert hasattr(mod, name), (mod.__name__, name)


def test_rest_lives_in_features_only():
    from app.platform.api import setup_routers

    assert setup_routers() is not None
    assert not list((ROOT_DIR / "api").rglob("*.py"))
