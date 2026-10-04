import asyncio
import hashlib

import aiohttp

from config import settings
from core.context import CommandContext
from core.registry import command

_MAX_SIZE = 20 * 1024 * 1024
_API_BASE = "https://www.virustotal.com/api/v3"
_ANALYSIS_TIMEOUT = 90
_ANALYSIS_POLL_DELAY = 5


def _extract_file(message):
    if message.document:
        return (
            message.document.file_id,
            message.document.file_size,
            message.document.file_name or "file",
        )
    if message.video:
        return message.video.file_id, message.video.file_size, "video.mp4"
    if message.audio:
        return (
            message.audio.file_id,
            message.audio.file_size,
            message.audio.file_name or "audio",
        )
    return None


async def _download(bot, file_id):
    file = await bot.get_file(file_id)
    buffer = await bot.download_file(file.file_path)
    return buffer.read()


async def _get_report(session, sha256):
    headers = {"x-apikey": settings.VT_API_KEY}
    async with session.get(f"{_API_BASE}/files/{sha256}", headers=headers) as resp:
        if resp.status == 200:
            return await resp.json()
        return None


async def _upload_file(session, data, filename):
    headers = {"x-apikey": settings.VT_API_KEY}
    form = aiohttp.FormData()
    form.add_field("file", data, filename=filename)
    async with session.post(f"{_API_BASE}/files", headers=headers, data=form) as resp:
        payload = await resp.json()
        return payload["data"]["id"]


async def _wait_for_analysis(session, analysis_id):
    headers = {"x-apikey": settings.VT_API_KEY}
    elapsed = 0
    while elapsed < _ANALYSIS_TIMEOUT:
        async with session.get(
            f"{_API_BASE}/analyses/{analysis_id}", headers=headers
        ) as resp:
            payload = await resp.json()
        status = payload["data"]["attributes"]["status"]
        if status == "completed":
            return payload
        await asyncio.sleep(_ANALYSIS_POLL_DELAY)
        elapsed += _ANALYSIS_POLL_DELAY
    return None


def _format_report(ctx, stats, sha256):
    malicious = stats.get("malicious", 0)
    suspicious = stats.get("suspicious", 0)
    harmless = stats.get("harmless", 0)
    undetected = stats.get("undetected", 0)
    total = malicious + suspicious + harmless + undetected
    verdict = (
        ctx.t("check.threats_found")
        if malicious or suspicious
        else ctx.t("check.no_threats")
    )
    detections = ctx.t("check.detections", count=malicious + suspicious, total=total)
    return f"{verdict}\n{detections}\nhttps://www.virustotal.com/gui/file/{sha256}"


@command(name="check", module="check")
async def cmd_check(ctx: CommandContext):
    if not settings.VT_API_KEY:
        await ctx.reply(ctx.t("check.not_configured"))
        return

    target = ctx.message.reply_to_message
    if not target:
        await ctx.usage_error(ctx.t("check.usage"))
        return

    extracted = _extract_file(target)
    if not extracted:
        await ctx.reply(ctx.t("check.no_file"))
        return

    file_id, file_size, filename = extracted
    if file_size and file_size > _MAX_SIZE:
        await ctx.reply(ctx.t("check.too_large"))
        return

    await ctx.reply(ctx.t("check.scanning"))

    data = await _download(ctx.bot, file_id)
    sha256 = hashlib.sha256(data).hexdigest()

    async with aiohttp.ClientSession() as session:
        report = await _get_report(session, sha256)

        if not report:
            analysis_id = await _upload_file(session, data, filename)
            analysis = await _wait_for_analysis(session, analysis_id)
            if not analysis:
                await ctx.reply(ctx.t("check.timeout"))
                return
            report = await _get_report(session, sha256)
            if not report:
                await ctx.reply(ctx.t("check.no_report"))
                return

    stats = report["data"]["attributes"]["last_analysis_stats"]
    await ctx.reply(_format_report(ctx, stats, sha256))
