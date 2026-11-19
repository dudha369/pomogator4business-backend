import importlib
import pkgutil

import commands
from app.features import FEATURES, feature_module


def load_commands():
    """Импорт регистрирует команды (декораторы `@command`) в registry."""
    for info in pkgutil.iter_modules(commands.__path__):
        importlib.import_module(f"commands.{info.name}")
    for feature in FEATURES:
        feature_module(feature, "bot")
