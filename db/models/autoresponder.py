from tortoise import fields
from tortoise.models import Model


class AutoresponderSettings(Model):
    """Одна строка на владельца — общие переключатели автоответчика.
    Текст приветствия/отсутствия и расписание — отдельно, здесь только
    состояние вкл/выкл для каждого режима."""

    owner_id = fields.BigIntField(pk=True, generated=False)
    greeting_enabled = fields.BooleanField(default=False)
    greeting_text = fields.TextField(null=True)
    away_enabled = fields.BooleanField(default=False)
    away_text = fields.TextField(null=True)
    away_start_minutes = fields.IntField(
        null=True
    )  # минуты от полуночи, локальное время владельца
    away_end_minutes = fields.IntField(null=True)
    auto_read_enabled = fields.BooleanField(default=False)

    class Meta:
        table = "autoresponder_settings"


class KeywordReply(Model):
    """Ответ по ключевому слову/фразе — проверяется по вхождению (без учёта
    регистра) в текст входящего сообщения."""

    id = fields.IntField(pk=True)
    owner_id = fields.BigIntField()
    keyword = fields.CharField(max_length=255)
    reply_text = fields.TextField()

    class Meta:
        table = "keyword_replies"
        unique_together = (("owner_id", "keyword"),)


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


class AutoresponderLog(Model):
    """Журнал отправленных автоответов — защита от спама и повторов:
    приветствие уходит одному собеседнику один раз, «нет на месте» — не чаще
    раза в несколько часов, ответ по ключевому слову — не чаще раза в
    несколько минут. Строки kind="greeting" хранятся вечно (иначе очистка
    заставила бы поприветствовать старого собеседника второй раз)."""

    id = fields.IntField(pk=True)
    owner_id = fields.BigIntField()
    chat_id = fields.BigIntField()
    kind = fields.CharField(max_length=16)  # greeting | away | keyword
    ref = fields.CharField(max_length=255, null=True)  # для keyword — само слово
    sent_at = fields.BigIntField()

    class Meta:
        table = "autoresponder_log"
        indexes = (("owner_id", "chat_id", "kind"),)


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
