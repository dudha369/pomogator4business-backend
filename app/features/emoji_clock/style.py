"""Описание одного стиля часов в эмодзи-статусе.

Стиль — это функция рисования (slot -> картинка 100x100) плюс метаданные.
Из метаданных выводится всё остальное: сколько нужно картинок и паков, как
называются паки в Telegram, какая картинка соответствует какой минуте суток.

Слот — минута, для которой нужна отдельная картинка («HH:MM»):
  * цифровые стили (hours=24): 1440 слотов, по картинке на каждую минуту суток;
  * аналоговые (hours=12): 720 слотов, 13:05 рисуется так же, как 01:05
    (как у настоящих часов). Паков в два раза меньше, загрузка в два раза быстрее.
"""

import re
from dataclasses import dataclass
from typing import Callable

CLOCK_PACK_SIZE = 180  # эмодзи в одном паке (лимит Telegram — 200)

# clock_<style>_v<revision>_<index>_by_<bot>; у старых паков такого вида нет
_PACK_NAME_RE = re.compile(
    r"^clock_(?P<style>.+)_v(?P<revision>\d+)_(?P<index>\d+)_by_"
)


def all_time_keys():
    """Все 1440 минут суток: '00:00' ... '23:59'."""
    return [f"{h:02d}:{m:02d}" for h in range(24) for m in range(60)]


def pack_revision(pack_name):
    """Ревизия дизайна, с которой собран пак. 0 — старые паки без ревизии в имени."""
    match = _PACK_NAME_RE.match(pack_name or "")
    return int(match["revision"]) if match else 0


@dataclass(frozen=True)
class ClockStyle:
    id: str
    # Номер версии дизайна. ПОВЫШАЙТЕ его при любом изменении картинок стиля:
    # ревизия входит в имя пака, поэтому clock_sync увидит, что паки устарели,
    # соберёт новые, переключит на них базу и удалит старые.
    revision: int
    titles: dict  # locale -> название в интерфейсе
    render: Callable  # (slot: "HH:MM") -> PIL.Image RGBA 100x100
    hours: int = 24  # 24 — цифровой (1440 картинок), 12 — аналоговый (720)
    sample: str = "21:00"  # время для превью

    @property
    def slots(self):
        return tuple(f"{h:02d}:{m:02d}" for h in range(self.hours) for m in range(60))

    @property
    def pack_count(self):
        return -(-len(self.slots) // CLOCK_PACK_SIZE)

    def slot_for(self, time_key):
        """Слот, чья картинка показывает время time_key ('HH:MM', 24-часовое)."""
        return f"{int(time_key[:2]) % self.hours:02d}:{time_key[3:5]}"

    def pack_slots(self, index):
        return self.slots[index * CLOCK_PACK_SIZE : (index + 1) * CLOCK_PACK_SIZE]

    def pack_name(self, index, bot_username):
        name = f"clock_{self.id}_v{self.revision}_{index}_by_{bot_username.lower()}"
        if len(name) > 64:
            raise ValueError(f"Имя пака длиннее 64 символов: {name}")
        return name

    def pack_title(self, index):
        return f"Clock · {self.titles['en']} {index + 1}/{self.pack_count}"
