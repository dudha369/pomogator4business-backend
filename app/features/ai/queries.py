from app.features.ai.models import AiDraft, AiSettings
from app.features.vault import service as vault

TABLE = "ai_drafts"


async def get_ai_settings(owner_id):
    rows = await AiSettings.filter(owner_id=owner_id).values()
    return rows[0] if rows else None


async def upsert_ai_settings(owner_id, **fields_):
    await AiSettings.update_or_create(owner_id=owner_id, defaults=fields_)


async def create_draft(owner_id, chat_id, source_message_id, text, created_at):
    sealed = await vault.seal_values(TABLE, owner_id, {"text": text})
    if sealed is None:  # шифрование сломалось: черновик без текста бесполезен
        raise RuntimeError("не удалось зашифровать черновик ИИ")
    row = await AiDraft.create(
        owner_id=owner_id,
        chat_id=chat_id,
        source_message_id=source_message_id,
        created_at=created_at,
        **sealed,
    )
    return row.id


async def get_draft(draft_id):
    rows = await AiDraft.filter(id=draft_id).values()
    return await vault.open_row(TABLE, rows[0]["owner_id"], rows[0]) if rows else None


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
