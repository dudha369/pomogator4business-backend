"""Ключи и шифрование значений. Без aiogram.

Правила (решения владельца):
- ключей нет и в БД нет шифротекста — шифрование выключено (пишется открытый текст);
- в БД есть шифротекст, а ключа нет или он неверный — приложение НЕ запускается;
- не удалось расшифровать отдельную запись — бот работает, запись без содержимого,
  владельцу приходит предупреждение `data_key_missing`;
- шифрование включено, но на записи сломалось — открытый текст НЕ пишется (`seal_values`
  возвращает None, вызывающий сохраняет только метаданные).

Значение хранится как `схема(1) | версия DEK(2) | nonce(12) | шифротекст`: версия есть в
каждой записи (для ротации), схема 1 — «ключ на сервере», 2 зарезервирована под ключ
пользователя (задача «Шифрование.2»). Текст и JSON лежат base64-строкой (тип колонки не
меняется), байты — как есть.
"""

import base64
import json
import logging
import time

from tortoise.exceptions import IntegrityError

from app.features.vault.models import OwnerKey
from app.features.vault.tables import BIN, JSON, TABLES
from app.platform.crypto import (
    CryptoError,
    aead_open,
    aead_seal,
    new_key,
    parse_master_keys,
)
from app.platform.tasks import spawn
from config import settings

logger = logging.getLogger("bot.vault")

SCHEME_SERVER = 1
_JSON_KEY = "$enc"
_HEADER_LEN = 3

_master: dict[int, bytes] = {}
_active_master: int | None = None
_deks: dict[tuple[int, int], bytes] = {}  # (owner, версия) -> DEK; ключи неизменны
_active: dict[int, tuple[int, bytes]] = {}  # owner -> (версия, DEK)
failed_owners: set[int] = (
    set()
)  # у кого есть нерасшифрованные записи (для alert-состояния)
_alerted: set[int] = set()


class VaultError(Exception):
    """Конфигурация шифрования неисправна: запускаться нельзя."""


def configure(raw: str) -> None:
    """Загружает мастер-ключи (первый — активный). Сбрасывает кэши ключей."""
    global _master, _active_master
    try:
        _master = parse_master_keys(raw)
    except CryptoError as exc:
        raise VaultError(str(exc)) from exc
    _active_master = next(iter(_master), None)
    _deks.clear()
    _active.clear()
    failed_owners.clear()
    _alerted.clear()


def enabled() -> bool:
    return _active_master is not None


def _wrap_aad(owner_id: int, version: int) -> bytes:
    return f"dek|{owner_id}|{version}".encode()


def _value_aad(owner_id: int, table: str, column: str) -> bytes:
    return f"{owner_id}|{table}.{column}".encode()


async def startup_check() -> None:
    """Проверка при старте (см. правила в docstring модуля)."""
    await startup_check_with(settings.DATA_MASTER_KEYS)


async def startup_check_with(raw_keys: str) -> None:
    configure(raw_keys)
    try:
        rows = await OwnerKey.all().values()
    except Exception as exc:
        if enabled():
            raise VaultError(
                "таблица owner_keys недоступна: примените миграцию (aerich upgrade)"
            ) from exc
        logger.warning("Шифрование выключено: DATA_MASTER_KEYS не задан")
        return
    if not rows:
        if not enabled():
            logger.warning("Шифрование выключено: DATA_MASTER_KEYS не задан")
        return
    if not enabled():
        raise VaultError(
            "в БД есть зашифрованные данные, но DATA_MASTER_KEYS не задан: "
            "верните ключи (данные не потеряны)"
        )
    for row in rows:
        master = _master.get(row["master_version"])
        if master is None:
            raise VaultError(
                f"нет мастер-ключа версии {row['master_version']} "
                f"(нужен для владельца {row['owner_id']}): верните его в DATA_MASTER_KEYS"
            )
        try:
            aead_open(
                master,
                _wrap_aad(row["owner_id"], row["version"]),
                bytes(row["wrapped_dek"]),
            )
        except CryptoError as exc:
            raise VaultError(
                f"мастер-ключ версии {row['master_version']} не подходит "
                f"к ключу владельца {row['owner_id']}"
            ) from exc
    stale = sum(1 for r in rows if r["master_version"] != _active_master)
    if stale:
        logger.info(
            "Ключей владельцев под старым мастер-ключом: %s (перепакуются)", stale
        )


async def _dek(owner_id: int, version: int) -> bytes | None:
    key = _deks.get((owner_id, version))
    if key is not None:
        return key
    rows = await OwnerKey.filter(owner_id=owner_id, version=version).values(
        "wrapped_dek", "master_version"
    )
    if not rows:
        return None
    master = _master.get(rows[0]["master_version"])
    if master is None:
        return None
    try:
        key = aead_open(
            master, _wrap_aad(owner_id, version), bytes(rows[0]["wrapped_dek"])
        )
    except CryptoError:
        return None
    _deks[(owner_id, version)] = key
    return key


async def _create_key(owner_id: int, version: int) -> None:
    dek = new_key()
    wrapped = aead_seal(_master[_active_master], _wrap_aad(owner_id, version), dek)
    try:
        await OwnerKey.create(
            owner_id=owner_id,
            version=version,
            wrapped_dek=wrapped,
            master_version=_active_master,
            created_at=int(time.time()),
        )
    except IntegrityError:
        # два процесса (деплой) создали одновременно: остаётся первый
        logger.info(
            "Ключ владельца %s v%s уже создан другим процессом", owner_id, version
        )


async def active_key(owner_id: int) -> tuple[int, bytes] | None:
    """(версия, DEK) для записи. Создаёт первый ключ владельца при необходимости."""
    cached = _active.get(owner_id)
    if cached:
        return cached
    rows = (
        await OwnerKey.filter(owner_id=owner_id)
        .order_by("-version")
        .limit(1)
        .values_list("version", flat=True)
    )
    if not rows:
        await _create_key(owner_id, 1)
        rows = [1]
    key = await _dek(owner_id, rows[0])
    if key is None:
        return None
    _active[owner_id] = (rows[0], key)
    return _active[owner_id]


async def rotate_owner_key(owner_id: int) -> int:
    """Новая версия DEK владельца. Старые остаются для чтения; записи перешифровывает
    `backfill.reencrypt_owner`. Возвращает новую версию."""
    if not enabled():
        raise VaultError("шифрование выключено")
    current = await active_key(owner_id)
    version = (current[0] if current else 0) + 1
    await _create_key(owner_id, version)
    _active.pop(owner_id, None)
    return version


async def owner_of(connection_id) -> int | None:
    from app.platform.sources import userbot_owner
    from db.models.connection import get_connection

    if (owner := userbot_owner(connection_id)) is not None:
        return owner

    row = await get_connection(connection_id)
    return row["owner_id"] if row else None


# --- кодирование значений ------------------------------------------------------------


def _encode(kind: str, value) -> bytes:
    if kind == BIN:
        return bytes(value)
    if kind == JSON:
        return json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode()
    return str(value).encode()


def _decode(kind: str, data: bytes):
    if kind == BIN:
        return data
    text = data.decode()
    return json.loads(text) if kind == JSON else text


def _pack(kind: str, version: int, blob: bytes):
    raw = bytes([SCHEME_SERVER]) + version.to_bytes(2, "big") + blob
    if kind == BIN:
        return raw
    text = base64.urlsafe_b64encode(raw).decode()
    # ORM не умеет хранить голую строку в JSON-колонке (считает её готовым JSON-текстом),
    # поэтому шифротекст кладём в объект
    return {_JSON_KEY: text} if kind == JSON else text


def _unpack(kind: str, stored) -> tuple[int, bytes]:
    if kind == BIN:
        raw = bytes(stored)
    else:
        if kind == JSON:
            if isinstance(stored, str):  # драйвер отдал JSON-текст как есть
                stored = json.loads(stored)
            stored = stored[_JSON_KEY]
        raw = base64.urlsafe_b64decode(stored)
    if len(raw) <= _HEADER_LEN or raw[0] != SCHEME_SERVER:
        raise CryptoError("неизвестная схема шифрования")
    return int.from_bytes(raw[1:_HEADER_LEN], "big"), raw[_HEADER_LEN:]


def seal_with(
    key: bytes, version: int, owner_id: int, table: str, values: dict
) -> dict:
    spec = TABLES[table]
    sealed = {}
    for column, value in values.items():
        kind = spec.columns[column]
        sealed[column] = (
            None
            if value is None
            else _pack(
                kind,
                version,
                aead_seal(
                    key, _value_aad(owner_id, table, column), _encode(kind, value)
                ),
            )
        )
    return sealed


async def seal_values(table: str, owner_id: int | None, values: dict) -> dict | None:
    """Зашифровать содержимое для записи в БД.

    Возвращает `{колонка: шифротекст, ..., "enc_ver": версия}`. Шифрование выключено —
    значения как есть и без `enc_ver`. Не вышло при включённом — None (и предупреждение):
    открытый текст в БД не попадёт."""
    if not enabled():
        return dict(values)
    try:
        key = await active_key(owner_id) if owner_id is not None else None
        if key is None:
            raise VaultError(f"нет ключа данных владельца {owner_id}")
        sealed = seal_with(key[1], key[0], owner_id, table, values)
    except Exception:
        logger.exception(
            "Не удалось зашифровать запись %s (владелец %s)", table, owner_id
        )
        _report_failure(owner_id)
        return None
    return {**sealed, "enc_ver": key[0]}


def _open_value(key: bytes, owner_id: int, table: str, column: str, stored):
    kind = TABLES[table].columns[column]
    _, blob = _unpack(kind, stored)
    return _decode(kind, aead_open(key, _value_aad(owner_id, table, column), blob))


async def open_row(table: str, owner_id: int | None, row: dict) -> dict:
    """Копия строки с расшифрованным содержимым и без служебного `enc_ver`. Открытая
    (старая) строка возвращается как есть. Не расшифровалось — колонки None."""
    row = dict(row)
    if row.pop("enc_ver", None) is None:
        return row
    spec = TABLES[table]
    for column in spec.columns:
        if row.get(column) is None:
            continue
        try:
            row[column] = await open_column(table, owner_id, column, row[column])
        except Exception:
            logger.error("Не расшифровать %s.%s (владелец %s)", table, column, owner_id)
            _report_failure(owner_id)
            row[column] = None
    return row


async def open_column(table: str, owner_id: int | None, column: str, stored):
    if owner_id is None:
        raise VaultError("владелец записи неизвестен")
    kind = TABLES[table].columns[column]
    version, _ = _unpack(kind, stored)
    key = await _dek(owner_id, version)
    if key is None:
        raise VaultError(f"нет ключа владельца {owner_id} v{version}")
    return _open_value(key, owner_id, table, column, stored)


async def open_rows(table: str, owner_id: int | None, rows) -> list[dict]:
    return [await open_row(table, owner_id, r) for r in rows]


async def open_by_connection(table: str, connection_id, rows) -> list[dict]:
    """Для таблиц с `connection_id`: владелец определяется по подключению один раз."""
    owner = await owner_of(connection_id) if rows else None
    return await open_rows(table, owner, rows)


async def open_one_by_connection(table: str, connection_id, row):
    return (
        await open_row(table, await owner_of(connection_id), row)
        if row is not None
        else None
    )


def _report_failure(owner_id: int | None) -> None:
    """Состояние `data_key_missing` — раз за процесс на владельца."""
    if owner_id is None or owner_id in _alerted:
        return
    _alerted.add(owner_id)
    failed_owners.add(owner_id)

    async def _send():
        from app.features.alerts.bot import report

        await report(owner_id, "data_key_missing")

    spawn(_send())


async def rewrap_keys() -> int:
    """Ротация мастер-ключа: DEK, обёрнутые не активным мастер-ключом, перепаковываются.
    Сами данные не трогаются. Нужного старого ключа нет — строка пропускается (лог)."""
    if not enabled():
        return 0
    done = 0
    for row in await OwnerKey.exclude(master_version=_active_master):
        old = _master.get(row.master_version)
        if old is None:
            logger.error(
                "Нет мастер-ключа v%s для владельца %s",
                row.master_version,
                row.owner_id,
            )
            continue
        aad = _wrap_aad(row.owner_id, row.version)
        row.wrapped_dek = aead_seal(
            _master[_active_master], aad, aead_open(old, aad, bytes(row.wrapped_dek))
        )
        row.master_version = _active_master
        await row.save(update_fields=["wrapped_dek", "master_version"])
        done += 1
    return done
