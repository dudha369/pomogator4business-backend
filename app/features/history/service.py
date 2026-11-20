import time

from tortoise import Tortoise
from tortoise.functions import Max

from app.features.history.models import MessageHistory, MessageLog
from app.features.history.snapshot import (
    FILE_KINDS,
    MAX_DOWNLOAD_BYTES,
    SNAPSHOT_COLUMNS,
)


async def save_history(
    connection_id,
    chat_id,
    message_id,
    is_owner,
    text,
    created_at,
    media_type=None,
    media_data=None,
    media_mime=None,
    media_name=None,
    media_status=None,
    snapshot=None,
):
    """Сохраняет (или обновляет при правке) сообщение.

    snapshot — результат app.features.history.adapter.build_snapshot; media_* — байты файла
    (нужны только для исчезающих медиа, обычные файлы достаются по file_id)."""
    snapshot = snapshot or {}
    if media_type is None and snapshot.get("kind") in FILE_KINDS:
        media_type = snapshot["kind"]
        media_mime = media_mime or snapshot.get("media_mime")
        media_name = media_name or snapshot.get("media_name")
    if media_type is not None and media_status is None:
        if media_data is not None:
            media_status = "saved"
        elif snapshot.get("file_id"):
            too_large = (snapshot.get("file_size") or 0) > MAX_DOWNLOAD_BYTES
            media_status = "too_large" if too_large else "remote"
        else:
            media_status = "failed"

    snap_values = {c: snapshot[c] for c in SNAPSHOT_COLUMNS if c in snapshot}
    obj, created = await MessageHistory.get_or_create(
        connection_id=connection_id,
        chat_id=chat_id,
        message_id=message_id,
        defaults={
            "is_owner": bool(is_owner),
            "text": text,
            "media_type": media_type,
            "media_data": media_data,
            "media_mime": media_mime,
            "media_name": media_name,
            "media_status": media_status,
            "created_at": created_at,
            **snap_values,
        },
    )
    if not created:
        obj.text = text
        update_fields = ["text"]
        if media_type is not None:
            obj.media_type = media_type
            obj.media_mime = media_mime
            obj.media_name = media_name
            obj.media_status = media_status
            update_fields += ["media_type", "media_mime", "media_name", "media_status"]

            if media_data is not None:
                obj.media_data = media_data
                update_fields.append("media_data")
        for column, value in snap_values.items():
            setattr(obj, column, value)
        update_fields += list(snap_values)
        await obj.save(update_fields=update_fields)


async def get_history_text(connection_id, chat_id, message_id):
    rows = await MessageHistory.filter(
        connection_id=connection_id, chat_id=chat_id, message_id=message_id
    ).values("text")
    return rows[0]["text"] if rows else None


async def get_history_entry(connection_id, chat_id, message_id):
    rows = await MessageHistory.filter(
        connection_id=connection_id, chat_id=chat_id, message_id=message_id
    ).values()
    return rows[0] if rows else None


async def set_history_transcript(connection_id, chat_id, message_id, text):
    await MessageHistory.filter(
        connection_id=connection_id, chat_id=chat_id, message_id=message_id
    ).update(transcript=text)


async def list_album(connection_id, chat_id, media_group_id):
    """Сообщения одного альбома, которые ещё лежат в истории (старые первыми)."""
    return await (
        MessageHistory.filter(
            connection_id=connection_id,
            chat_id=chat_id,
            media_group_id=media_group_id,
        )
        .order_by("message_id")
        .values()
    )


async def delete_history(connection_id, chat_id, message_id):
    await MessageHistory.filter(
        connection_id=connection_id, chat_id=chat_id, message_id=message_id
    ).delete()


async def has_other_messages(connection_id, chat_id, exclude_message_id):
    return (
        await MessageHistory.filter(connection_id=connection_id, chat_id=chat_id)
        .exclude(message_id=exclude_message_id)
        .exists()
    )


async def get_recent_history(connection_id, chat_id, limit):
    rows = (
        await MessageHistory.filter(connection_id=connection_id, chat_id=chat_id)
        .order_by("-created_at")
        .limit(limit)
        .values(
            "id",
            "connection_id",
            "chat_id",
            "message_id",
            "is_owner",
            "text",
            "media_type",
            "created_at",
        )
    )
    return list(reversed(rows))


async def list_last_incoming_by_chat(connection_id):
    return (
        await MessageHistory.filter(connection_id=connection_id, is_owner=False)
        .group_by("chat_id")
        .annotate(last_message_id=Max("message_id"), last_at=Max("created_at"))
        .values("chat_id", "last_message_id", "last_at")
    )


async def list_recent_chats(connection_id, limit):
    return (
        await MessageHistory.filter(connection_id=connection_id)
        .group_by("chat_id")
        .annotate(last_at=Max("created_at"))
        .order_by("-last_at")
        .limit(limit)
        .values("chat_id", "last_at")
    )


async def _query(sql, params):
    """Сырой SQL с одинаковыми {1},{2}… для SQLite (?) и Postgres ($n): агрегаты,
    которые ORM выразит хуже (оконная функция, деление дат)."""
    conn = Tortoise.get_connection("default")
    postgres = conn.capabilities.dialect == "postgres"
    marks = {f"p{i}": (f"${i}" if postgres else "?") for i in range(1, len(params) + 1)}
    return await conn.execute_query_dict(sql.format(**marks), list(params))


async def last_rows_by_chat(connection_id, since_ts):
    """По одной (последней) строке на чат: хватает, чтобы понять, кто ждёт ответа,
    и не тащит в память всю историю окна."""
    return await _query(
        "SELECT chat_id, message_id, is_owner, created_at FROM ("
        " SELECT chat_id, message_id, is_owner, created_at,"
        "  ROW_NUMBER() OVER (PARTITION BY chat_id"
        "   ORDER BY created_at DESC, message_id DESC) AS rn"
        " FROM message_history WHERE connection_id = {p1} AND created_at >= {p2}"
        ") t WHERE rn = 1",
        (connection_id, since_ts),
    )


async def count_by_day(connection_id, since_ts, offset_minutes):
    """[{day, is_owner, n}]: сообщения по локальным суткам (day — число суток с 1970-01-01)."""
    return await _query(
        "SELECT (created_at + {p1}) / 86400 AS day, is_owner, COUNT(*) AS n"
        " FROM message_history WHERE connection_id = {p2} AND created_at >= {p3}"
        " GROUP BY 1, 2",
        (int(offset_minutes) * 60, connection_id, since_ts),
    )


MAX_REPLY_GAP_SECONDS = 24 * 3600  # ответ позже суток не считаем «скоростью ответа»


async def reply_gaps(connection_id, since_ts):
    """Секунды от первого неотвеченного входящего до ответа владельца — по одному
    числу на каждую «серию» входящих в чате. Серия = сообщения между двумя ответами
    владельца (k — число ответов владельца строго до строки). Ответ позже суток и
    ответ без входящего не учитываются. Считает БД: в память идут только эти числа."""
    rows = await _query(
        "SELECT reply_at - first_in AS gap FROM ("
        " SELECT MIN(CASE WHEN is_owner THEN NULL ELSE created_at END) AS first_in,"
        "  MIN(CASE WHEN is_owner THEN created_at END) AS reply_at"
        " FROM ("
        "  SELECT chat_id, is_owner, created_at,"
        "   SUM(CASE WHEN is_owner THEN 1 ELSE 0 END) OVER (PARTITION BY chat_id"
        "    ORDER BY created_at, message_id"
        "    ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING) AS k"
        "  FROM message_history WHERE connection_id = {p1} AND created_at >= {p2}"
        " ) t GROUP BY chat_id, COALESCE(k, 0)"
        ") g WHERE first_in IS NOT NULL AND reply_at IS NOT NULL"
        " AND reply_at - first_in BETWEEN 0 AND {p3}",
        (connection_id, since_ts, MAX_REPLY_GAP_SECONDS),
    )
    return [int(r["gap"]) for r in rows]


async def count_by_chat(connection_id, since_ts):
    """[{chat_id, is_owner, n}] — активность по собеседникам."""
    return await _query(
        "SELECT chat_id, is_owner, COUNT(*) AS n FROM message_history"
        " WHERE connection_id = {p1} AND created_at >= {p2} GROUP BY 1, 2",
        (connection_id, since_ts),
    )


async def list_chat_history(connection_id, chat_id, limit):
    rows = (
        await MessageHistory.filter(connection_id=connection_id, chat_id=chat_id)
        .order_by("-created_at", "-message_id")
        .limit(limit)
        .values("message_id", "is_owner", "text", "created_at")
    )
    return list(reversed(rows))


async def last_owner_message_at(connection_id, chat_id):
    rows = (
        await MessageHistory.filter(
            connection_id=connection_id, chat_id=chat_id, is_owner=True
        )
        .order_by("-created_at")
        .limit(1)
        .values_list("created_at", flat=True)
    )
    return rows[0] if rows else None


async def count_messages_since(connection_id, since_ts):
    query = MessageHistory.filter(connection_id=connection_id, created_at__gte=since_ts)
    total = await query.count()
    incoming = await query.filter(is_owner=False).count()
    return total, incoming


async def purge_history(older_than_ts):
    return await MessageHistory.filter(created_at__lt=older_than_ts).delete()


async def expire_history_media(older_than_ts):
    return await MessageHistory.filter(
        created_at__lt=older_than_ts, media_data__not_isnull=True
    ).update(media_data=None, media_status="expired")


async def get_history_media(connection_id, chat_id, message_id):
    rows = await MessageHistory.filter(
        connection_id=connection_id, chat_id=chat_id, message_id=message_id
    ).values("media_type", "media_data", "media_mime", "media_name")
    return rows[0] if rows else None


async def list_media_flags(connection_id, pairs):
    if not pairs:
        return {}
    from tortoise.expressions import Q

    condition = Q()
    for chat_id, message_id in pairs:
        condition |= Q(chat_id=chat_id, message_id=message_id)
    base = MessageHistory.filter(
        condition, connection_id=connection_id, media_type__not_isnull=True
    )
    rows = await base.values(
        "chat_id",
        "message_id",
        "media_type",
        "media_mime",
        "media_name",
        "media_status",
    )
    with_data = set(
        await base.filter(media_data__not_isnull=True).values_list(
            "chat_id", "message_id"
        )
    )
    return {
        (r["chat_id"], r["message_id"]): {
            **r,
            "available": (r["chat_id"], r["message_id"]) in with_data,
        }
        for r in rows
    }


async def log_message(connection_id, chat_id, message_id):
    await MessageLog.create(
        connection_id=connection_id,
        chat_id=chat_id,
        message_id=message_id,
        created_at=int(time.time()),
    )


async def recent_message_log(connection_id, chat_id, count):
    """Последние `count` записей журнала как [(log_id, message_id)], БЕЗ удаления:
    стирать журнал можно только после того, как сообщения реально удалены."""
    rows = (
        await MessageLog.filter(connection_id=connection_id, chat_id=chat_id)
        .order_by("-log_id")
        .limit(count)
        .values_list("log_id", "message_id")
    )
    return [tuple(row) for row in rows]


async def forget_message_log(log_ids):
    if log_ids:
        await MessageLog.filter(log_id__in=list(log_ids)).delete()


async def trim_message_log(keep):
    """Оставляет по `keep` последних записей журнала НА КАЖДОЕ подключение (он нужен лишь для
    .del и подобных команд, которым важны свежие сообщения). Возвращает число
    удалённых строк."""
    removed = 0
    connection_ids = (
        await MessageLog.all().distinct().values_list("connection_id", flat=True)
    )
    for connection_id in connection_ids:  # у каждого подключения свой «хвост»
        rows = (
            await MessageLog.filter(connection_id=connection_id)
            .order_by("-log_id")
            .offset(keep)
            .limit(1)
            .values_list("log_id", flat=True)
        )
        if rows:
            removed += await MessageLog.filter(
                connection_id=connection_id, log_id__lte=rows[0]
            ).delete()
    return removed


async def expire_message_log(older_than_ts):
    """Удаляет записи журнала старше порога (записи без времени не трогает)."""
    return await MessageLog.filter(created_at__lt=older_than_ts).delete()


async def scrub_raw_json(limit):
    """Обнуляет raw_json у текстов и файлов — он нужен только экзотическим типам,
    а новые строки его уже не получают. Порция в `limit` строк; возвращает число
    обнулённых."""
    ids = (
        await MessageHistory.filter(
            raw_json__not_isnull=True, kind__in=["text", *FILE_KINDS]
        )
        .limit(limit)
        .values_list("id", flat=True)
    )
    if not ids:
        return 0
    return await MessageHistory.filter(id__in=list(ids)).update(raw_json=None)
