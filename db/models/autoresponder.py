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
