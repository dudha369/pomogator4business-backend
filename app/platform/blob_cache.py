"""LRU-кэш готовых файлов (байты, mime) с TTL: для эмодзи и стикеров интерфейса.

Файл не меняется, а «нет такого» может быть временным сбоем Telegram, поэтому
найденное живёт долго, отсутствующее — недолго. Переполнение вытесняет самую давнюю
запись, а не сбрасывает всё."""

import time
from collections import OrderedDict

Blob = tuple[bytes, str]


class BlobCache:
    def __init__(
        self, max_entries: int = 500, ttl_found: int = 24 * 3600, ttl_missing: int = 600
    ):
        self.max_entries = max_entries
        self.ttl_found = ttl_found
        self.ttl_missing = ttl_missing
        self._items: OrderedDict[str, tuple[float, Blob | None]] = OrderedDict()

    def get(self, key: str) -> tuple[bool, Blob | None]:
        """(есть ли живая запись, значение); значение None — запомненное «нет»."""
        hit = self._items.get(key)
        if hit and hit[0] > time.monotonic():
            self._items.move_to_end(key)
            return True, hit[1]
        return False, None

    def put(self, key: str, value: Blob | None) -> None:
        ttl = self.ttl_found if value else self.ttl_missing
        self._items[key] = (time.monotonic() + ttl, value)
        self._items.move_to_end(key)
        while len(self._items) > self.max_entries:
            self._items.popitem(last=False)

    def keys(self) -> list[str]:
        return list(self._items)

    def clear(self) -> None:
        self._items.clear()
