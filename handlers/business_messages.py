"""Бизнес-сообщения: цепочка middleware + диспетчер команд.

Порядок регистрации = порядок обработки (прежний конвейер):
  контекст (outer) → журнал владельца → спасение медиа → история → расшифровка голосовых →
  эффект голосовых → новый контакт → mute → автоответчик → эхо → type-триггеры → команда.
Шаги живут рядом со своей логикой; здесь только их порядок."""

from aiogram import Router

from app.features.archive.bot.transcript import voice_transcript
from app.features.history.bot import record_history, rescue_replied_media
from app.features.mute.bot import mute_gate
from app.platform.telegram.dispatch import dispatch_command
from app.platform.telegram.incoming import load_incoming, owner_journal
from commands.echo import echo_step
from commands.scam import new_contact_step
from commands.type_ import type_trigger_step
from commands.voice_effects import voice_step
from core.autoresponder import autoresponder_step

STEPS = (
    owner_journal,
    rescue_replied_media,
    record_history,
    voice_transcript,
    voice_step,
    new_contact_step,
    mute_gate,
    autoresponder_step,
    echo_step,
    type_trigger_step,
)


def build_router() -> Router:
    router = Router(name="business_messages")
    observer = router.business_message
    observer.outer_middleware(load_incoming)
    for step in STEPS:
        observer.middleware(step)
    observer.register(dispatch_command)
    return router


router = build_router()
