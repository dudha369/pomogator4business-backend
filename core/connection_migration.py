"""Перенос данных владельца на новое подключение бота.

При переподключении Telegram выдаёт новый business_connection_id. Всё, что
привязано к подключению (архив и история, выключенные модули, эхо, мьюты,
состояния игр, резервная копия профиля), осталось бы на старом id, а
вкладка «Архив» открывалась бы пустой. Настройки по owner_id (автоответчик,
алиасы, избранное, язык) от этого не страдают.

Решение: при появлении нового подключения владельца переписываем
connection_id во всех таблицах, где он есть, и копируем префикс."""

import logging

from tortoise import Tortoise

from db.models.connection import Connection

logger = logging.getLogger("bot.connection_migration")


def _all_models():
    apps = Tortoise.apps
    # в Tortoise 1.x реестр — объект Apps, в старых версиях — словарь словарей
    if hasattr(apps, "get_models_iterable"):
        return list(apps.get_models_iterable())
    return [model for app in apps.values() for model in app.values()]


def _models_with_connection_id():
    for model in _all_models():
        if model is Connection:
            continue
        if "connection_id" in model._meta.fields_map:
            yield model


async def adopt_previous_connection(new_connection_id: str, owner_id: int):
    """Переносит данные с последнего прежнего подключения владельца на новое.
    Возвращает {"from": старый_id, "moved": {таблица: строк}} или None, если
    прежних подключений не было."""
    previous = (
        await Connection.filter(owner_id=owner_id)
        .exclude(connection_id=new_connection_id)
        .order_by("-created_at")
        .limit(1)
        .values("connection_id", "prefix")
    )
    if not previous:
        return None
    old_id, old_prefix = previous[0]["connection_id"], previous[0]["prefix"]

    await Connection.filter(connection_id=new_connection_id).update(prefix=old_prefix)

    moved = {}
    for model in _models_with_connection_id():
        table = model._meta.db_table
        try:
            count = await model.filter(connection_id=old_id).update(
                connection_id=new_connection_id
            )
        except Exception:
            # например, конфликт уникальности, если на новом id уже есть строки;
            # данные остаются на старом id, остальное переносим дальше
            logger.warning("Не удалось перенести %s с %s", table, old_id, exc_info=True)
            continue
        if count:
            moved[table] = count

    logger.info("Подключение %s → %s: перенесено %s", old_id, new_connection_id, moved)
    return {"from": old_id, "moved": moved}
