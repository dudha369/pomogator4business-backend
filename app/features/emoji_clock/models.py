from tortoise import fields
from tortoise.models import Model

from app.features.emoji_clock import DEFAULT_STYLE_ID as DEFAULT_CLOCK_STYLE


class ClockPack(Model):
    """Один эмодзи-пак Telegram. Пак принадлежит стилю часов (style)."""

    id = fields.IntField(pk=True)
    style = fields.CharField(max_length=32, default=DEFAULT_CLOCK_STYLE)
    pack_index = fields.IntField()
    pack_name = fields.CharField(max_length=255)
    uploaded_count = fields.IntField(default=0)
    completed = fields.BooleanField(default=False)

    class Meta:
        table = "clock_packs"
        unique_together = (("style", "pack_index"),)


class ClockEmoji(Model):
    """Соответствие «стиль + минута суток -> custom_emoji_id»."""

    id = fields.IntField(pk=True)
    style = fields.CharField(max_length=32, default=DEFAULT_CLOCK_STYLE)
    time_key = fields.CharField(max_length=16)
    pack_index = fields.IntField()
    custom_emoji_id = fields.CharField(max_length=255, null=True)

    class Meta:
        table = "clock_emojis"
        unique_together = (("style", "time_key"),)


class EmojiStatusSetting(Model):
    owner_id = fields.BigIntField(pk=True, generated=False)
    granted = fields.BooleanField(default=False)
    enabled = fields.BooleanField(default=False)
    clock_style = fields.CharField(max_length=32, default=DEFAULT_CLOCK_STYLE)

    class Meta:
        table = "emoji_status_settings"
