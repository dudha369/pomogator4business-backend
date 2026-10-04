import random

from aiogram import F, Router
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup

from core import database as db
from core.i18n import t
from core.registry import command

router = Router(name="rps")

_CHOICES = ["rock", "scissors", "paper"]
_EMOJI = {"rock": "🪨", "scissors": "✂️", "paper": "📄"}
_BEATS = {"rock": "scissors", "scissors": "paper", "paper": "rock"}


def _keyboard():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text=_EMOJI[c], callback_data=f"rps:{c}")
                for c in _CHOICES
            ]
        ]
    )


@command(name="rps", module="rps", owner_only=False)
async def cmd_rps(ctx):
    await ctx.edit_command_message(
        t("rps.prompt", ctx.locale), reply_markup=_keyboard()
    )


@router.callback_query(F.data.startswith("rps:"))
async def on_rps_callback(call: CallbackQuery):
    choice = call.data.split(":", 1)[1]
    if choice not in _CHOICES:
        await call.answer()
        return

    connection = await db.get_connection(call.message.business_connection_id)
    locale = await db.get_locale(connection["owner_id"]) if connection else "ru"

    bot_choice = random.choice(_CHOICES)

    if choice == bot_choice:
        result = t("rps.draw", locale)
    elif _BEATS[choice] == bot_choice:
        result = t("rps.win", locale)
    else:
        result = t("rps.lose", locale)

    text = t(
        "rps.result",
        locale,
        player=_EMOJI[choice],
        bot=_EMOJI[bot_choice],
        result=result,
    )

    await call.message.edit_text(text, reply_markup=_keyboard())
    await call.answer()
