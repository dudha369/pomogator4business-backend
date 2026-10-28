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


async def list_templates(owner_id):
    return (
        await QuickTemplate.filter(owner_id=owner_id)
        .order_by("name")
        .values("name", "text")
    )


async def get_template(owner_id, name):
    rows = await QuickTemplate.filter(owner_id=owner_id, name=name).values_list(
        "text", flat=True
    )
    return rows[0] if rows else None


async def count_templates(owner_id):
    return await QuickTemplate.filter(owner_id=owner_id).count()


async def save_template(owner_id, name, text):
    await QuickTemplate.update_or_create(
        owner_id=owner_id, name=name, defaults={"text": text}
    )


async def delete_template(owner_id, name):
    return bool(await QuickTemplate.filter(owner_id=owner_id, name=name).delete())
