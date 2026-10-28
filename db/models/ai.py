from tortoise import fields
from tortoise.models import Model


class AiSettings(Model):
    owner_id = fields.BigIntField(pk=True)
    enabled = fields.BooleanField(default=False)
    # draft — бот присылает владельцу черновик с кнопками; auto — отвечает сам
    mode = fields.CharField(max_length=8, default="draft")
    instructions = fields.TextField(null=True)
    history_messages = fields.IntField(default=10)
    daily_limit = fields.IntField(default=30)

    class Meta:
        table = "ai_settings"


class AiDraft(Model):
    """Черновик ответа ИИ, ожидающий решения владельца."""

    id = fields.IntField(pk=True)
    owner_id = fields.BigIntField()
    chat_id = fields.BigIntField()
    source_message_id = fields.BigIntField()
    text = fields.TextField()
    created_at = fields.BigIntField()
    status = fields.CharField(
        max_length=16, default="pending"
    )  # pending | sent | dismissed

    class Meta:
        table = "ai_drafts"


async def get_ai_settings(owner_id):
    rows = await AiSettings.filter(owner_id=owner_id).values()
    return rows[0] if rows else None


async def upsert_ai_settings(owner_id, **fields_):
    await AiSettings.update_or_create(owner_id=owner_id, defaults=fields_)


async def create_draft(owner_id, chat_id, source_message_id, text, created_at):
    row = await AiDraft.create(
        owner_id=owner_id,
        chat_id=chat_id,
        source_message_id=source_message_id,
        text=text,
        created_at=created_at,
    )
    return row.id


async def get_draft(draft_id):
    rows = await AiDraft.filter(id=draft_id).values()
    return rows[0] if rows else None


async def set_draft_status(draft_id, status):
    """Атомарно меняет pending → status. True, только если черновик был pending
    (защита от двойного нажатия «Отправить»)."""
    return bool(
        await AiDraft.filter(id=draft_id, status="pending").update(status=status)
    )


async def set_draft_status_force(draft_id, status):
    """Безусловно выставляет статус (откат после неудачной отправки)."""
    await AiDraft.filter(id=draft_id).update(status=status)


async def purge_old_drafts(older_than_ts):
    return await AiDraft.filter(created_at__lt=older_than_ts).delete()
