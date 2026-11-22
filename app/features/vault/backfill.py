"""Шифрование старых (открытых) строк и перешифровка под новую версию DEK.

Пакетами и по одной строке: каждая строка — короткая транзакция с `SELECT … FOR UPDATE`
(на Postgres блокируется одна строка на миллисекунды, на SQLite без эффекта), условие
`enc_ver IS NULL` гарантирует, что строку, которую уже записал шаг конвейера, не затрут."""

import asyncio
import logging
from importlib import import_module

from tortoise.transactions import in_transaction

from app.features.vault import service
from app.features.vault.tables import TABLES

logger = logging.getLogger("bot.vault")

_BATCH = 200


def _model(table: str):
    module, _, name = TABLES[table].model.partition(":")
    return getattr(import_module(module), name)


async def reseal_row(table: str, pk_value) -> bool:
    """Зашифровать строку активным ключом владельца, если она открытая или под старой
    версией DEK. True — строка изменена. Исключение — расшифровать старое не вышло."""
    spec = TABLES[table]
    async with in_transaction():
        row = (
            await _model(table)
            .filter(**{spec.pk: pk_value})
            .select_for_update()
            .first()
        )
        if row is None:
            return False
        owner = (
            row.owner_id
            if spec.owner_by == "owner_id"
            else await service.owner_of(row.connection_id)
        )
        key = await service.active_key(owner) if owner is not None else None
        if key is None or (row.enc_ver is not None and row.enc_ver >= key[0]):
            return False
        values = {}
        for column in spec.columns:
            value = getattr(row, column)
            if value is None:
                continue
            if row.enc_ver is not None:
                value = await service.open_column(table, owner, column, value)
            values[column] = value
        sealed = service.seal_with(key[1], key[0], owner, table, values)
        for column in spec.columns:
            setattr(row, column, sealed.get(column))
        row.enc_ver = key[0]
        await row.save(update_fields=[*spec.columns, "enc_ver"])
    return True


async def seal_legacy(table: str, **filters) -> None:
    """Зашифровать открытые строки, подходящие под фильтр (горячий путь: перед правкой
    одной колонки у строки, которую ещё не успел обработать бэкфилл)."""
    if not service.enabled():
        return
    spec = TABLES[table]
    ids = (
        await _model(table)
        .filter(enc_ver__isnull=True, **filters)
        .values_list(spec.pk, flat=True)
    )
    for pk in ids:
        try:
            await reseal_row(table, pk)
        except Exception:
            logger.exception("Не удалось зашифровать %s %s", table, pk)


async def _sweep(table: str, limit: int, **filters) -> int:
    spec, model, done, cursor = TABLES[table], _model(table), 0, 0
    while done < limit:
        ids = (
            await model.filter(**{f"{spec.pk}__gt": cursor}, **filters)
            .order_by(spec.pk)
            .limit(min(_BATCH, limit - done))
            .values_list(spec.pk, flat=True)
        )
        if not ids:
            break
        for pk in ids:
            cursor = pk
            try:
                done += await reseal_row(table, pk)
            except Exception:
                logger.exception("Не удалось зашифровать %s %s", table, pk)
        await asyncio.sleep(0)  # не держим цикл событий между пакетами
    return done


async def backfill(limit: int) -> int:
    """Шифрует открытые строки всех таблиц, не больше `limit` на таблицу за проход."""
    if not service.enabled():
        return 0
    total = 0
    for table in TABLES:
        total += await _sweep(table, limit, enc_ver__isnull=True)
    return total


async def reencrypt_owner(owner_id: int) -> int:
    """После `rotate_owner_key`: строки владельца под старой версией DEK -> новая."""
    from db.models.connection import Connection

    version = (await service.active_key(owner_id))[0]
    connections = await Connection.filter(owner_id=owner_id).values_list(
        "connection_id", flat=True
    )
    total = 0
    for table, spec in TABLES.items():
        owner_filter = (
            {"owner_id": owner_id}
            if spec.owner_by == "owner_id"
            else {"connection_id__in": list(connections)}
        )
        total += await _sweep(
            table,
            10**9,
            enc_ver__isnull=False,
            enc_ver__lt=version,
            **owner_filter,
        )
    return total
