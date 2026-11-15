from tortoise import fields
from tortoise.models import Model


class QuickTemplate(Model):
    """Шаблон быстрого ответа: `.t имя` подставляет текст в сообщение."""

    id = fields.IntField(pk=True)
    owner_id = fields.BigIntField()
    name = fields.CharField(max_length=32)
    text = fields.TextField()

    class Meta:
        table = "quick_templates"
        unique_together = (("owner_id", "name"),)
