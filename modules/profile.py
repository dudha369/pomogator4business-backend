import logging
import time

from aiogram.types import BufferedInputFile, InputProfilePhotoStatic

from core.context import CommandContext
from core.media import download_user_avatar
from core.registry import command
from core import database as db

logger = logging.getLogger("bot.profile")


async def _get_bio(bot, user_id):
    try:
        chat_info = await bot.get_chat(user_id)
        return getattr(chat_info, "bio", None)
    except Exception:
        logger.warning("Не удалось получить био пользователя %s", user_id, exc_info=True)
        return None


@command(
    name="profile",
    aliases=["профиль"],
    module="profile",
)
async def cmd_profile(ctx: CommandContext):
    target = ctx.message.reply_to_message
    if not target or not target.from_user:
        await ctx.usage_error(ctx.t("profile.usage_reply"))
        return

    owner_id = ctx.connection["owner_id"]

    current_bio = await _get_bio(ctx.bot, owner_id)
    current_photo = await download_user_avatar(ctx.bot, owner_id)
    owner = ctx.message.from_user  # команду пишет владелец — это его текущее имя
    await db.save_profile_backup(
        ctx.connection_id,
        current_bio,
        current_photo,
        int(time.time()),
        first_name=owner.first_name if owner else None,
        last_name=owner.last_name if owner else None,
    )

    target_user_id = target.from_user.id
    target_bio = await _get_bio(ctx.bot, target_user_id)
    target_photo = await download_user_avatar(ctx.bot, target_user_id)

    applied = []

    # Имя: username не копируем — он уникален. Копируем имя и фамилию.
    if target.from_user.first_name:
        try:
            await ctx.bot.set_business_account_name(
                business_connection_id=ctx.connection_id,
                first_name=target.from_user.first_name,
                last_name=target.from_user.last_name,
            )
            applied.append(ctx.t("profile.item_name"))
        except Exception:
            logger.warning("Не удалось скопировать имя", exc_info=True)

    if target_bio is not None:
        try:
            await ctx.bot.set_business_account_bio(
                business_connection_id=ctx.connection_id, bio=target_bio
            )
            applied.append(ctx.t("profile.item_bio"))
        except Exception:
            logger.warning("Не удалось скопировать био", exc_info=True)

    if target_photo:
        try:
            await ctx.bot.set_business_account_profile_photo(
                business_connection_id=ctx.connection_id,
                photo=InputProfilePhotoStatic(
                    photo=BufferedInputFile(target_photo, filename="avatar.jpg")
                ),
            )
            applied.append(ctx.t("profile.item_avatar"))
        except Exception:
            logger.warning("Не удалось скопировать аватар", exc_info=True)

    if applied:
        await ctx.edit_command_message(
            ctx.t("profile.copied", items=", ".join(applied))
        )
    else:
        await ctx.edit_command_message(ctx.t("profile.copy_failed"))


@command(
    name="restore",
    aliases=["восстановить"],
    module="profile",
)
async def cmd_restore(ctx: CommandContext):
    backup = await db.get_profile_backup(ctx.connection_id)
    if not backup:
        await ctx.reply(ctx.t("profile.no_backup"))
        return

    restored = []

    if backup.get("first_name"):
        try:
            await ctx.bot.set_business_account_name(
                business_connection_id=ctx.connection_id,
                first_name=backup["first_name"],
                last_name=backup.get("last_name"),
            )
            restored.append(ctx.t("profile.item_name"))
        except Exception:
            logger.warning("Не удалось восстановить имя", exc_info=True)

    if backup["bio"] is not None:
        try:
            await ctx.bot.set_business_account_bio(
                business_connection_id=ctx.connection_id, bio=backup["bio"]
            )
            restored.append(ctx.t("profile.item_bio"))
        except Exception:
            logger.warning("Не удалось восстановить био", exc_info=True)

    if backup["photo_data"]:
        try:
            await ctx.bot.set_business_account_profile_photo(
                business_connection_id=ctx.connection_id,
                photo=InputProfilePhotoStatic(
                    photo=BufferedInputFile(backup["photo_data"], filename="avatar.jpg")
                ),
            )
            restored.append(ctx.t("profile.item_avatar"))
        except Exception:
            logger.warning("Не удалось восстановить аватар", exc_info=True)

    if restored:
        await ctx.edit_command_message(
            ctx.t("profile.restored", items=", ".join(restored))
        )
    else:
        await ctx.edit_command_message(ctx.t("profile.restore_failed"))
