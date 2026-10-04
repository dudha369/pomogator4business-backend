import time

from aiogram.types import BufferedInputFile, InputProfilePhotoStatic

from core.context import CommandContext
from core.media import download_user_avatar
from core.registry import command
from core import database as db


async def _get_bio(bot, user_id):
    try:
        chat_info = await bot.get_chat(user_id)
        return getattr(chat_info, "bio", None)
    except Exception:
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
    await db.save_profile_backup(
        ctx.connection_id, current_bio, current_photo, int(time.time())
    )

    target_user_id = target.from_user.id
    target_bio = await _get_bio(ctx.bot, target_user_id)
    target_photo = await download_user_avatar(ctx.bot, target_user_id)

    applied = []

    if target_bio is not None:
        try:
            await ctx.bot.set_business_account_bio(
                business_connection_id=ctx.connection_id, bio=target_bio
            )
            applied.append(ctx.t("profile.item_bio"))
        except Exception:
            pass

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
            pass

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

    if backup["bio"] is not None:
        try:
            await ctx.bot.set_business_account_bio(
                business_connection_id=ctx.connection_id, bio=backup["bio"]
            )
            restored.append(ctx.t("profile.item_bio"))
        except Exception:
            pass

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
            pass

    if restored:
        await ctx.edit_command_message(
            ctx.t("profile.restored", items=", ".join(restored))
        )
    else:
        await ctx.edit_command_message(ctx.t("profile.restore_failed"))
