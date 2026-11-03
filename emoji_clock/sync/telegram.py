"""Вызовы Telegram для работы с эмодзи-паками.

Лимиты Telegram действуют на бота целиком, поэтому при flood-limit
(retry_after) останавливаются ВСЕ параллельные загрузки, а не одна: общий
«шлагбаум» одного экземпляра Telegram.
"""

import asyncio
import time

from aiogram.exceptions import TelegramBadRequest, TelegramRetryAfter
from aiogram.types import BufferedInputFile, InputSticker

EMOJI_LIST = ["🕐"]  # эмодзи-«подпись» стикера, на вид часов не влияет


def input_sticker(slot, png_bytes):
    return InputSticker(
        sticker=BufferedInputFile(png_bytes, filename=f"{slot.replace(':', '-')}.png"),
        format="static",
        emoji_list=EMOJI_LIST,
    )


class Telegram:
    def __init__(self, bot, retry_padding=1.0, log=print):
        self.bot = bot
        self.retry_padding = retry_padding  # запас сверх retry_after, сек
        self.log = log
        self.flood_waits = 0
        self._blocked_until = 0.0

    async def call(self, factory):
        """Выполнить вызов; при flood-limit подождать (вместе со всеми) и повторить."""
        while True:
            wait = self._blocked_until - time.monotonic()
            if wait > 0:
                await asyncio.sleep(wait)
            try:
                return await factory()
            except TelegramRetryAfter as exc:
                self.flood_waits += 1
                delay = exc.retry_after + self.retry_padding
                self._blocked_until = max(self._blocked_until, time.monotonic() + delay)
                self.log(
                    f"  flood-limit: пауза {delay:.0f} с (всего пауз: {self.flood_waits})"
                )

    async def get_set(self, name):
        """Набор или None, если такого нет."""
        try:
            return await self.call(lambda: self.bot.get_sticker_set(name))
        except TelegramBadRequest as exc:
            if (
                "STICKERSET_INVALID" in str(exc).upper()
                or "not found" in str(exc).lower()
            ):
                return None
            raise

    async def create_set(self, owner_id, name, title, stickers):
        return await self.call(
            lambda: self.bot.create_new_sticker_set(
                user_id=owner_id,
                name=name,
                title=title,
                stickers=stickers,
                sticker_type="custom_emoji",
                needs_repainting=True,  # Telegram перекрашивает эмодзи в цвет текста
            )
        )

    async def add_sticker(self, owner_id, name, sticker):
        return await self.call(
            lambda: self.bot.add_sticker_to_set(
                user_id=owner_id, name=name, sticker=sticker
            )
        )

    async def delete_set(self, name):
        return await self.call(lambda: self.bot.delete_sticker_set(name))
