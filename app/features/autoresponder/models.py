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
