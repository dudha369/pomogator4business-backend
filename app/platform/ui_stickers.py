"""Реестр стикеров интерфейса: смысловое имя -> где взять файл.

Добавить стикер = одна строка в REGISTRY. Идентификаторы нигде больше не хранятся.
Получить значения: отправьте стикер (или сообщение с премиум-эмодзи) боту в личку
от администратора, бот ответит готовой строкой.

`file_id` стикера привязан к конкретному боту и здесь не годится. Храним:
- `sticker(set_name, file_unique_id)` — обычный стикер набора; `file_id` для нашего бота
  берётся из `getStickerSet` (набор может быть любым, в том числе нашим собственным);
- `emoji(custom_emoji_id)` — кастомное эмодзи, глобальный числовой id.
"""

from dataclasses import dataclass
from enum import StrEnum


@dataclass(frozen=True)
class StickerRef:
    emoji_id: str | None = None
    set_name: str | None = None
    unique_id: str | None = None


def emoji(custom_emoji_id: str) -> StickerRef:
    return StickerRef(emoji_id=custom_emoji_id)


def sticker(set_name: str, file_unique_id: str) -> StickerRef:
    return StickerRef(set_name=set_name, unique_id=file_unique_id)


REGISTRY: dict[str, StickerRef] = {
    "error_forbidden": sticker("UtyaDuck", "AgADWhYAAqKeqUk"),  # уточка, запрет
    "error_crying": sticker("UtyaDuck", "AgADRh4AAvyUOEk"),  # уточка плачет
}

# Имена для OpenAPI: из реестра, поэтому TypeScript-тип обновляется сам.
StickerName = StrEnum("StickerName", {name: name for name in REGISTRY})
