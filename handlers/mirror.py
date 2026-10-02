from aiogram import Router
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message

from core import database as db
from core.i18n import t
from core.mirror_manager import mirror_manager
from core.mirror_setup import MirrorSetupError, connect_mirror

router = Router(name="mirror_setup")


class MirrorState(StatesGroup):
    waiting_for_token = State()


@router.message(Command("mirror"))
async def cmd_mirror(message: Message, state: FSMContext):
    locale = await db.get_locale(message.from_user.id)
    existing = await db.get_mirror(message.from_user.id)
    if existing and existing["is_active"]:
        await message.answer(
            t("mirror.already_connected", locale, username=existing["bot_username"])
        )
        return

    await message.answer(t("mirror.onboarding", locale))
    await state.set_state(MirrorState.waiting_for_token)


@router.message(Command("unmirror"))
async def cmd_unmirror(message: Message):
    locale = await db.get_locale(message.from_user.id)
    existing = await db.get_mirror(message.from_user.id)
    if not existing:
        await message.answer(t("mirror.not_connected", locale))
        return

    await mirror_manager.stop_mirror(message.from_user.id)
    await db.delete_mirror(message.from_user.id)
    await message.answer(t("mirror.disconnected", locale))


@router.message(Command("cancel"), StateFilter(MirrorState.waiting_for_token))
async def cmd_cancel(message: Message, state: FSMContext):
    locale = await db.get_locale(message.from_user.id)
    await state.clear()
    await message.answer(t("mirror.cancelled", locale))


@router.message(StateFilter(MirrorState.waiting_for_token))
async def on_token_received(message: Message, state: FSMContext):
    locale = await db.get_locale(message.from_user.id)
    token = message.text.strip() if message.text else ""

    try:
        username = await connect_mirror(message.from_user.id, token)
    except MirrorSetupError as exc:
        key = (
            "mirror.invalid_token_format"
            if exc.code == "invalid_format"
            else "mirror.connection_failed"
        )
        await message.answer(t(key, locale))
        return

    await state.clear()
    await message.answer(t("mirror.connected_success", locale, username=username))
