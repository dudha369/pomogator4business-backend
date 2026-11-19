from app.features.autoresponder.models import (
    AutoresponderLog,
    AutoresponderSettings,
    KeywordReply,
)


async def get_autoresponder_settings(owner_id):
    rows = await AutoresponderSettings.filter(owner_id=owner_id).values()
    return rows[0] if rows else None


async def upsert_autoresponder_settings(owner_id, **fields):
    await AutoresponderSettings.update_or_create(owner_id=owner_id, defaults=fields)


async def list_keyword_replies(owner_id):
    return await KeywordReply.filter(owner_id=owner_id).order_by("keyword").values()


async def add_keyword_reply(owner_id, keyword, reply_text):
    await KeywordReply.update_or_create(
        owner_id=owner_id, keyword=keyword.lower(), defaults={"reply_text": reply_text}
    )


async def delete_keyword_reply(owner_id, keyword):
    await KeywordReply.filter(owner_id=owner_id, keyword=keyword.lower()).delete()


async def last_autoreply_at(owner_id, chat_id, kind, ref=None):
    """Время последнего автоответа этого вида в чате или None."""
    query = AutoresponderLog.filter(owner_id=owner_id, chat_id=chat_id, kind=kind)
    if ref is not None:
        query = query.filter(ref=ref)
    rows = await query.order_by("-sent_at").limit(1).values_list("sent_at", flat=True)
    return rows[0] if rows else None


async def last_autoreply_ref(owner_id, chat_id, kind):
    """ref самой свежей записи этого вида в чате (или None)."""
    rows = (
        await AutoresponderLog.filter(owner_id=owner_id, chat_id=chat_id, kind=kind)
        .order_by("-sent_at", "-id")
        .limit(1)
        .values_list("ref", flat=True)
    )
    return rows[0] if rows else None


async def count_autoreplies_since(owner_id, kind, since_ts):
    """Сколько автоответов этого вида отправлено с момента since_ts."""
    return await AutoresponderLog.filter(
        owner_id=owner_id, kind=kind, sent_at__gte=since_ts
    ).count()


async def log_autoreply(owner_id, chat_id, kind, ref, sent_at):
    await AutoresponderLog.create(
        owner_id=owner_id, chat_id=chat_id, kind=kind, ref=ref, sent_at=sent_at
    )


async def purge_autoresponder_log(older_than_ts):
    """Чистит всё, кроме приветствий (см. docstring модели)."""
    return (
        await AutoresponderLog.filter(sent_at__lt=older_than_ts)
        .exclude(kind="greeting")
        .delete()
    )


async def count_keyword_replies(owner_id):
    return await KeywordReply.filter(owner_id=owner_id).count()
