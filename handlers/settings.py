from aiogram import F, Router
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from core import database as db
from core.i18n import LANGUAGE_NAMES, t
from core.registry import registry
from core.webapp import webapp_keyboard

router = Router(name="settings")

_ONBOARDING_PROMPT = "Выберите язык / Choose language / Оберіть мову"


class PrefixState(StatesGroup):
    waiting_for_prefix = State()


def _settings_keyboard(locale):
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✏️", callback_data="settings:prefix")],
            [InlineKeyboardButton(text="🧩", callback_data="settings:modules")],
        ]
    )


def _modules_keyboard(disabled):
    buttons = []
    for module_name in sorted(registry.modules().keys()):
        is_on = module_name not in disabled
        label = f"{'✅' if is_on else '⛔️'} {module_name}"
        buttons.append(
            [
                InlineKeyboardButton(
                    text=label, callback_data=f"settings:toggle:{module_name}"
                )
            ]
        )
    buttons.append([InlineKeyboardButton(text="⬅️", callback_data="settings:back")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def _language_keyboard(onboarding=False):
    suffix = ":onboarding" if onboarding else ""
    buttons = [
        [InlineKeyboardButton(text=name, callback_data=f"language:{code}{suffix}")]
        for code, name in LANGUAGE_NAMES.items()
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)


async def _send_greeting(target, owner_id, locale, edit=False):
    connection = await db.get_connection_by_owner(owner_id)
    if connection and connection["is_enabled"]:
        text = t("start.greeting_connected", locale)
        markup = webapp_keyboard(t("connection.open_app_button", locale))
    else:
        text = t("start.greeting", locale)
        markup = None

    if edit:
        await target.edit_text(text, reply_markup=markup)
    else:
        await target.answer(text, reply_markup=markup)


@router.message(Command("start"))
async def cmd_start(message: Message):
    owner_id = message.from_user.id

    if not await db.has_chosen_locale(owner_id):
        await message.answer(
            _ONBOARDING_PROMPT, reply_markup=_language_keyboard(onboarding=True)
        )
        return

    locale = await db.get_locale(owner_id)
    await _send_greeting(message, owner_id, locale)


@router.message(Command("language"))
async def cmd_language(message: Message):
    locale = await db.get_locale(message.from_user.id)
    await message.answer(t("language.title", locale), reply_markup=_language_keyboard())


@router.callback_query(F.data.startswith("language:"))
async def cb_language(call: CallbackQuery):
    parts = call.data.split(":")
    new_locale = parts[1]
    onboarding = len(parts) > 2 and parts[2] == "onboarding"

    await db.set_locale(call.from_user.id, new_locale)

    if onboarding:
        await _send_greeting(call.message, call.from_user.id, new_locale, edit=True)
    else:
        await call.message.edit_text(t("language.updated", new_locale))

    await call.answer()


@router.message(Command("archive"))
async def cmd_archive_view(message: Message):
    locale = await db.get_locale(message.from_user.id)
    connection = await db.get_connection_by_owner(message.from_user.id)
    if not connection:
        await message.answer(t("common.not_connected", locale))
        return

    entries = await db.get_recent_archive(connection["connection_id"], 20)
    if not entries:
        await message.answer(t("settings.archive_empty", locale))
        return

    lines = []
    for entry in entries:
        icon = "🗑" if entry["event"] == "deleted" else "✏️"
        lines.append(f"{icon} chat {entry['chat_id']}: {entry['old_text']!r}")

    await message.answer(t("settings.archive_header", locale) + "\n".join(lines))


@router.message(Command("settings"))
async def cmd_settings(message: Message):
    locale = await db.get_locale(message.from_user.id)
    connection = await db.get_connection_by_owner(message.from_user.id)
    if not connection:
        await message.answer(t("common.connect_first", locale))
        return

    await message.answer(
        t("settings.current_prefix", locale, prefix=connection["prefix"]),
        reply_markup=_settings_keyboard(locale),
    )


@router.callback_query(F.data == "settings:back")
async def cb_back(call: CallbackQuery):
    locale = await db.get_locale(call.from_user.id)
    connection = await db.get_connection_by_owner(call.from_user.id)
    if not connection:
        await call.answer(t("common.connection_not_found", locale), show_alert=True)
        return

    await call.message.edit_text(
        t("settings.current_prefix", locale, prefix=connection["prefix"]),
        reply_markup=_settings_keyboard(locale),
    )
    await call.answer()


@router.callback_query(F.data == "settings:prefix")
async def cb_prefix(call: CallbackQuery, state: FSMContext):
    locale = await db.get_locale(call.from_user.id)
    await call.message.edit_text(t("settings.enter_new_prefix", locale))
    await state.set_state(PrefixState.waiting_for_prefix)
    await call.answer()


@router.message(StateFilter(PrefixState.waiting_for_prefix))
async def on_new_prefix(message: Message, state: FSMContext):
    locale = await db.get_locale(message.from_user.id)
    new_prefix = message.text.strip()
    if len(new_prefix) != 1:
        await message.answer(t("settings.prefix_single_char", locale))
        return

    connection = await db.get_connection_by_owner(message.from_user.id)
    if not connection:
        await message.answer(t("common.not_connected", locale))
        await state.clear()
        return

    await db.set_prefix(connection["connection_id"], new_prefix)
    await state.clear()
    await message.answer(
        t("settings.prefix_updated", locale, prefix=new_prefix),
        reply_markup=_settings_keyboard(locale),
    )


@router.callback_query(F.data == "settings:modules")
async def cb_modules(call: CallbackQuery):
    locale = await db.get_locale(call.from_user.id)
    connection = await db.get_connection_by_owner(call.from_user.id)
    if not connection:
        await call.answer(t("common.connection_not_found", locale), show_alert=True)
        return

    disabled = await db.list_disabled_modules(connection["connection_id"])
    await call.message.edit_text(
        t("settings.modules_title", locale),
        reply_markup=_modules_keyboard(disabled),
    )
    await call.answer()


@router.callback_query(F.data.startswith("settings:toggle:"))
async def cb_toggle(call: CallbackQuery):
    locale = await db.get_locale(call.from_user.id)
    module_name = call.data.split(":", 2)[2]

    connection = await db.get_connection_by_owner(call.from_user.id)
    if not connection:
        await call.answer(t("common.connection_not_found", locale), show_alert=True)
        return

    disabled = await db.list_disabled_modules(connection["connection_id"])
    if module_name in disabled:
        await db.enable_module(connection["connection_id"], module_name)
    else:
        await db.disable_module(connection["connection_id"], module_name)

    disabled = await db.list_disabled_modules(connection["connection_id"])
    await call.message.edit_reply_markup(reply_markup=_modules_keyboard(disabled))
    await call.answer()
