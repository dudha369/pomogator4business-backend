from app.features.voice_effects.models import VoiceEffect


async def get_voice_effect(connection_id, chat_id):
    rows = await VoiceEffect.filter(
        connection_id=connection_id, chat_id=chat_id
    ).values("effect")
    return rows[0]["effect"] if rows else None


async def set_voice_effect(connection_id, chat_id, effect):
    if effect is None:
        await VoiceEffect.filter(connection_id=connection_id, chat_id=chat_id).delete()
    else:
        await VoiceEffect.update_or_create(
            connection_id=connection_id, chat_id=chat_id, defaults={"effect": effect}
        )
