"""Запросы к таблицам архива (`archive_log`, `archive_prefs`) — без логики и без aiogram."""

from tortoise.expressions import Q

from app.features.archive.models import ArchiveLog, ArchivePrefs
from app.features.vault import service as vault
from config import settings

TABLE = "archive_log"


def _ids(connection_id) -> list[str]:
    """Один `connection_id` или список (у владельца бизнес-бот и юзербот — два)."""
    return [connection_id] if isinstance(connection_id, str) else list(connection_id)


async def _open(connection_id, rows):
    # у всех подключений одного владельца общий ключ данных: берём любое
    return await vault.open_by_connection(TABLE, _ids(connection_id)[0], rows)


LIST_COLUMNS = (
    "log_id",
    "connection_id",
    "chat_id",
    "message_id",
    "event",
    "old_text",
    "new_text",
    "media_type",
    "media_mime",
    "media_name",
    "media_status",
    "kind",
    "is_owner",
    "edit_kind",
    "old_snapshot",
    "new_snapshot",
    "created_at",
    "enc_ver",
)


async def log_archive_event(
    connection_id,
    chat_id,
    message_id,
    event,
    old_text,
    new_text,
    created_at,
    media_type=None,
    media_data=None,
    media_mime=None,
    media_name=None,
    media_status=None,
    kind=None,
    edit_kind=None,
    old_snapshot=None,
    new_snapshot=None,
    notice_message_id=None,
    is_owner=False,
):
    if media_type is not None and media_status is None:
        media_status = "saved" if media_data is not None else "failed"
    content = {
        "old_text": old_text,
        "new_text": new_text,
        "media_data": media_data,
        "media_name": media_name,
        "old_snapshot": old_snapshot,
        "new_snapshot": new_snapshot,
    }
    owner_id = await vault.owner_of(connection_id) if vault.enabled() else None
    sealed = await vault.seal_values(TABLE, owner_id, content)
    if sealed is None:  # шифрование сломалось: событие сохраняем без содержимого
        sealed = dict.fromkeys(content)
    row = await ArchiveLog.create(
        connection_id=connection_id,
        chat_id=chat_id,
        message_id=message_id,
        event=event,
        media_type=media_type,
        media_mime=media_mime,
        media_status=media_status,
        kind=kind,
        is_owner=is_owner,
        edit_kind=edit_kind,
        notice_message_id=notice_message_id,
        created_at=created_at,
        **sealed,
    )
    return row.log_id


async def get_recent_archive(connection_id, limit):
    rows = (
        await ArchiveLog.filter(connection_id=connection_id)
        .order_by("-log_id")
        .limit(limit)
        .values(*LIST_COLUMNS)
    )
    return await _open(connection_id, rows)


async def get_archive_page(
    connection_id,
    before_id,
    limit,
    event=None,
    search=None,
    chat_id=None,
    date_from=None,
    date_to=None,
    ascending=False,
):
    query = ArchiveLog.filter(connection_id__in=_ids(connection_id))
    if before_id is not None:
        if ascending:
            query = query.filter(log_id__gt=before_id)
        else:
            query = query.filter(log_id__lt=before_id)
    if event is not None:
        query = query.filter(event=event)
    if chat_id is not None:
        query = query.filter(chat_id=chat_id)
    if date_from is not None:
        query = query.filter(created_at__gte=date_from)
    if date_to is not None:
        query = query.filter(created_at__lte=date_to)
    ordering = "log_id" if ascending else "-log_id"
    if search and vault.enabled():
        # шифротекст в SQL не ищется: просматриваем свежие записи порциями и фильтруем
        # расшифрованное в Python (не больше ARCHIVE_SEARCH_SCAN записей)
        ids = await _search_ids(
            query.order_by(ordering), _ids(connection_id)[0], search, limit + 1
        )
        rows = (
            await ArchiveLog.filter(log_id__in=ids)
            .order_by(ordering)
            .values(*LIST_COLUMNS)
            if ids
            else []
        )
    else:
        if search:
            query = query.filter(
                Q(old_text__icontains=search) | Q(new_text__icontains=search)
            )
        rows = await query.order_by(ordering).limit(limit + 1).values(*LIST_COLUMNS)
    has_more = len(rows) > limit
    return await _open(connection_id, rows[:limit]), has_more


_SEARCH_BATCH = 500


async def _search_ids(ordered_query, connection_id, search, want):
    """log_id записей, где в старом или новом тексте есть `search` (без учёта регистра)."""
    needle = search.casefold()
    owner = await vault.owner_of(connection_id)
    found, scanned = [], 0
    while len(found) < want and scanned < settings.ARCHIVE_SEARCH_SCAN:
        batch = (
            await ordered_query.offset(scanned)
            .limit(_SEARCH_BATCH)
            .values("log_id", "old_text", "new_text", "enc_ver")
        )
        if not batch:
            break
        scanned += len(batch)
        for row in await vault.open_rows(TABLE, owner, batch):
            texts = (row["old_text"] or "", row["new_text"] or "")
            if any(needle in text.casefold() for text in texts):
                found.append(row["log_id"])
                if len(found) == want:
                    break
    return found


async def count_archive_events_since(connection_id, since_ts):
    base = ArchiveLog.filter(connection_id=connection_id, created_at__gte=since_ts)
    return {
        "deleted": await base.filter(event="deleted").count(),
        "edited": await base.filter(event="edited").count(),
    }


async def purge_archive(older_than_ts):
    return await ArchiveLog.filter(created_at__lt=older_than_ts).delete()


async def list_log_media_availability(connection_id, log_ids):
    if not log_ids:
        return set()
    return set(
        await ArchiveLog.filter(
            connection_id=connection_id,
            log_id__in=list(log_ids),
            media_data__not_isnull=True,
        ).values_list("log_id", flat=True)
    )


async def get_log_media(connection_id, log_id):
    rows = await ArchiveLog.filter(
        connection_id__in=_ids(connection_id), log_id=log_id
    ).values(
        "log_id",
        "connection_id",
        "event",
        "old_snapshot",
        "new_snapshot",
        "chat_id",
        "message_id",
        "media_type",
        "media_mime",
        "media_name",
        "media_status",
        "media_data",
        "enc_ver",
    )
    return (await _open(connection_id, rows))[0] if rows else None


async def expire_archive_media(older_than_ts):
    return await ArchiveLog.filter(
        created_at__lt=older_than_ts, media_data__not_isnull=True
    ).update(media_data=None, media_status="expired")


async def get_edit_history(connection_id, chat_id, message_id):
    """Все правки одного сообщения (старые первыми): тексты, снимки (там сущности),
    время, id уведомления."""
    rows = await (
        ArchiveLog.filter(
            connection_id=connection_id,
            chat_id=chat_id,
            message_id=message_id,
            event="edited",
        )
        .order_by("log_id")
        .values(
            "log_id",
            "old_text",
            "new_text",
            "old_snapshot",
            "new_snapshot",
            "edit_kind",
            "notice_message_id",
            "created_at",
            "enc_ver",
        )
    )
    return await _open(connection_id, rows)


async def get_archive_prefs_data(connection_id):
    row = await ArchivePrefs.get_or_none(connection_id=connection_id)
    return row.data if row else {}


async def save_archive_prefs_data(connection_id, data):
    await ArchivePrefs.update_or_create(
        connection_id=connection_id, defaults={"data": data}
    )
