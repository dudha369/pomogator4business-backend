from tortoise import fields
from tortoise.models import Model


class UserbotSession(Model):
    """Сессия юзербота владельца (одна на владельца).

    `session` — строка Telethon `StringSession`, то есть ПОЛНЫЙ доступ к аккаунту:
    хранится только шифротекстом (vault, `enc_ver`), открытым текстом не пишется никогда.
    Номер телефона не храним."""

    owner_id = fields.BigIntField(pk=True, generated=False)
    session = fields.TextField(null=True)  # шифротекст; None — сессии нет (отозвана)
    enc_ver = fields.SmallIntField(null=True)
    # active — работает; removing — владелец отключил, ждёт log_out на сервере с блокировкой;
    # revoked — Telegram завершил сеанс (нужен новый вход)
    status = fields.CharField(max_length=16, default="active")
    connected = fields.BooleanField(
        default=False
    )  # последнее известное состояние связи
    tg_user_id = fields.BigIntField(null=True)
    tg_username = fields.CharField(max_length=64, null=True)
    consent_at = fields.BigIntField()
    created_at = fields.BigIntField()
    last_error = fields.CharField(max_length=64, null=True)  # короткий код, без текста

    class Meta:
        table = "userbot_sessions"
