from tortoise import fields
from tortoise.models import Model


class LinkscanSettings(Model):
    """Настройки проверки ссылок владельца. Выключено по умолчанию: проверка в
    сети отправляет адреса из переписки сторонним сервисам."""

    owner_id = fields.BigIntField(pk=True, generated=False)
    enabled = fields.BooleanField(default=False)
    scope = fields.CharField(max_length=8, default="all")  # "all" | "selected"
    # False — не обращаться к внешним сервисам (Google, abuse.ch, VirusTotal): работают только
    # проверки на сервере бота, ничего из переписки наружу не уходит
    external = fields.BooleanField(default=True)

    class Meta:
        table = "linkscan_settings"


class LinkscanChat(Model):
    """Чат, выбранный для проверки (используется при scope = "selected")."""

    id = fields.IntField(pk=True)
    owner_id = fields.BigIntField()
    chat_id = fields.BigIntField()

    class Meta:
        table = "linkscan_chats"
        unique_together = (("owner_id", "chat_id"),)


class LinkscanCache(Model):
    """Ответ одного провайдера на один адрес или хеш файла. Ключ — sha256 адреса
    (для файла — sha256 файла), так что сами адреса из переписки не хранятся."""

    id = fields.IntField(pk=True)
    provider = fields.CharField(max_length=16)
    kind = fields.CharField(max_length=4)  # "url" | "file"
    key = fields.CharField(max_length=64)
    level = fields.IntField()
    reasons = fields.JSONField(default=list)
    expires_at = fields.BigIntField(db_index=True)

    class Meta:
        table = "linkscan_cache"
        unique_together = (("provider", "kind", "key"),)
