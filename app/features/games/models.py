from tortoise import fields
from tortoise.models import Model


class GameSession(Model):
    """Одна партия мини-игры в чате: по строке на (подключение, чат, игра).

    `status` и `message_id` вынесены в колонки (по ним ищут и сверяют сообщение
    с кнопками), остальное состояние — в `state` (JSON, схема у каждой игры своя,
    см. `service.GAME_DEFAULTS`).
    """

    id = fields.IntField(pk=True)
    connection_id = fields.CharField(max_length=255)
    chat_id = fields.BigIntField()
    game = fields.CharField(max_length=16)
    status = fields.CharField(max_length=16, default="active")
    message_id = fields.BigIntField(null=True)
    state = fields.JSONField(default=dict)

    class Meta:
        table = "game_sessions"
        unique_together = (("connection_id", "chat_id", "game"),)
