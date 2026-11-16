"""Транспорт архива: роутеры удалений, правок и кнопок собраны в один `router`."""

from aiogram import Router

from app.features.archive.bot import callbacks, deleted, edited
from app.platform.telegram.registry import registry

registry.register_passive_module("archive")

router = Router(name="archive")
router.include_routers(deleted.router, edited.router, callbacks.router)
