"""Автоответчик: приветствие новому собеседнику, режим «нет на месте» по
расписанию, ответы по ключевым словам, авто-прочтение.

Структура: чистые функции (`in_away_window`, `pick_keyword`, `render`,
`build_candidates`) без обращений к БД/Telegram — их легко тестировать, —
и один оркестратор `handle_incoming`, который собирает факты, выбирает ответ
и отправляет. На каждое входящее сообщение уходит не больше ОДНОГО автоответа
(приоритет: ключевое слово → «нет на месте» → приветствие).

ИИ (core/ai.py) подключается последним: если не сработало ни одно правило.

Защита от спама и циклов:
- не отвечаем ботам и не-личным чатам;
- не отвечаем на сообщения-команды (начинаются с префикса);
- не отвечаем, если владелец сам писал в чат в последние 10 минут (для
  «нет на месте» — он явно на связи);
- кулдауны хранятся в БД (autoresponder_log), а не в памяти — переживают
  перезапуск: приветствие — один раз на собеседника, «нет на месте» — раз в
  6 часов, ключевое слово — раз в 5 минут на слово.
"""

import logging
import time
from dataclasses import dataclass

from core import ai
from core import database as db

logger = logging.getLogger("bot.autoresponder")

AWAY_COOLDOWN_SECONDS = 6 * 3600
KEYWORD_COOLDOWN_SECONDS = 300
OWNER_ACTIVE_WINDOW_SECONDS = 600
MAX_REPLY_LENGTH = 4096  # лимит Telegram на длину сообщения


_NO_SETTINGS = {
    "greeting_enabled": False,
    "greeting_text": None,
    "away_enabled": False,
    "away_text": None,
    "away_start_minutes": None,
    "away_end_minutes": None,
    "auto_read_enabled": False,
}


@dataclass(frozen=True)
class AutoReply:
    kind: str  # "keyword" | "away" | "greeting"
    ref: str | None
    text: str


# --------------------------- чистая логика ---------------------------------


def in_away_window(now_ts: int, offset_minutes: int, start, end) -> bool:
    """Попадает ли текущий момент в окно «нет на месте».

    start/end — минуты от локальной полуночи владельца. Окно может переходить
    через полночь (22:00–08:00). Если расписание не задано (оба None) или
    start == end — режим действует круглосуточно."""
    if start is None or end is None or start == end:
        return True
    local_minutes = ((now_ts + offset_minutes * 60) % 86400) // 60
    if start < end:
        return start <= local_minutes < end
    return local_minutes >= start or local_minutes < end


def pick_keyword(text: str, keywords):
    """Самое длинное (то есть самое конкретное) ключевое слово, входящее в
    текст без учёта регистра; None, если ничего не подошло."""
    lowered = text.lower()
    matches = [k for k in keywords if k["keyword"] and k["keyword"] in lowered]
    return max(matches, key=lambda k: len(k["keyword"])) if matches else None


def render(template: str, user) -> str:
    """Подставляет {name}/{first_name}/{full_name}. Не использует str.format,
    чтобы любые другие фигурные скобки в тексте остались как есть."""
    first = getattr(user, "first_name", None) or ""
    full = getattr(user, "full_name", None) or first
    return (
        template.replace("{first_name}", first)
        .replace("{full_name}", full)
        .replace("{name}", first)
    )


def build_candidates(
    *,
    settings,
    keywords,
    text,
    is_command,
    is_new_contact,
    owner_recently_active,
    now,
    tz_offset,
    user,
):
    """Подходящие автоответы в порядке приоритета (кулдауны — не здесь)."""
    result = []

    if text and not is_command:
        hit = pick_keyword(text, keywords)
        if hit:
            result.append(
                AutoReply("keyword", hit["keyword"], render(hit["reply_text"], user))
            )

    away_text = (settings.get("away_text") or "").strip()
    if (
        settings.get("away_enabled")
        and away_text
        and not owner_recently_active
        and not is_command
        and in_away_window(
            now,
            tz_offset,
            settings.get("away_start_minutes"),
            settings.get("away_end_minutes"),
        )
    ):
        result.append(AutoReply("away", None, render(away_text, user)))

    greeting_text = (settings.get("greeting_text") or "").strip()
    if (
        settings.get("greeting_enabled")
        and greeting_text
        and is_new_contact
        and not is_command
    ):
        result.append(AutoReply("greeting", None, render(greeting_text, user)))

    return result


# ------------------------------ оркестратор --------------------------------


async def _cooldown_ok(owner_id, chat_id, reply: AutoReply, now: int) -> bool:
    last = await db.last_autoreply_at(owner_id, chat_id, reply.kind, reply.ref)
    if last is None:
        return True
    if reply.kind == "greeting":
        return False  # приветствие — один раз навсегда
    window = AWAY_COOLDOWN_SECONDS if reply.kind == "away" else KEYWORD_COOLDOWN_SECONDS
    return now - last >= window


async def _auto_read(bot, connection, message):
    try:
        if await db.is_favorite_chat(connection["owner_id"], message.chat.id):
            return  # избранные чаты остаются непрочитанными — это их смысл
        await bot.read_business_message(
            business_connection_id=connection["connection_id"],
            chat_id=message.chat.id,
            message_id=message.message_id,
        )
    except Exception:
        logger.warning("auto-read chat=%s", message.chat.id, exc_info=True)


async def handle_incoming(bot, connection, message, now=None) -> AutoReply | None:
    """Вызывается для входящего (не от владельца) сообщения. Возвращает
    отправленный автоответ или None.
    Любые сбои логируются и не прерывают обработку сообщения."""
    user = message.from_user
    if (
        user is None
        or user.is_bot
        or getattr(message.chat, "type", "private") != "private"
    ):
        return None

    owner_id = connection["owner_id"]
    # строки настроек может не быть (например, включён только ИИ) — берём «всё выключено»
    settings = await db.get_autoresponder_settings(owner_id) or _NO_SETTINGS

    if settings["auto_read_enabled"]:
        await _auto_read(bot, connection, message)

    chat_id = message.chat.id
    flags = await db.get_chat_flags(owner_id, chat_id)
    if flags["no_autoreply"]:
        return None  # чат в режиме «не беспокоить» (авто-прочтение выше — по своей настройке)

    text = message.text or message.caption or ""
    is_command = bool(text) and text.startswith(connection["prefix"])

    keywords = (
        await db.list_keyword_replies(owner_id) if text and not is_command else []
    )
    ai_settings = await db.get_ai_settings(owner_id)
    ai_on = bool(
        ai_settings
        and ai_settings["enabled"]
        and ai.is_configured()
        and text
        and not is_command
        and not flags["no_ai"]
    )
    if not (
        settings["greeting_enabled"] or settings["away_enabled"] or keywords or ai_on
    ):
        return None

    now = int(now if now is not None else time.time())
    last_owner_at = await db.last_owner_message_at(connection["connection_id"], chat_id)
    # «новый собеседник»: ни владелец, ни он сам раньше в этом чате не писали
    # (по сохранённой истории) и приветствия ему ещё не отправлялись
    is_new_contact = last_owner_at is None and not await db.has_other_messages(
        connection["connection_id"], chat_id, message.message_id
    )
    owner_recently_active = (
        last_owner_at is not None and now - last_owner_at < OWNER_ACTIVE_WINDOW_SECONDS
    )

    candidates = build_candidates(
        settings=settings,
        keywords=keywords,
        text=text,
        is_command=is_command,
        is_new_contact=is_new_contact,
        owner_recently_active=owner_recently_active,
        now=now,
        tz_offset=await db.get_timezone_offset(owner_id),
        user=user,
    )

    for reply in candidates:
        if not await _cooldown_ok(owner_id, chat_id, reply, now):
            continue
        try:
            sent = await bot.send_message(
                business_connection_id=connection["connection_id"],
                chat_id=chat_id,
                text=reply.text[:MAX_REPLY_LENGTH],
            )
        except Exception:
            logger.warning(
                "Не удалось отправить автоответ chat=%s", chat_id, exc_info=True
            )
            return None

        await db.log_message(connection["connection_id"], chat_id, sent.message_id)
        await db.log_autoreply(owner_id, chat_id, reply.kind, reply.ref, now)
        if is_new_contact and reply.kind != "greeting":
            # первое сообщение уже получило ответ — приветствовать задним числом не нужно
            await db.log_autoreply(owner_id, chat_id, "greeting", None, now)
        return reply

    # Ничего из «правил» не подошло — последний рубеж: ИИ (если включён)
    if ai_on and not owner_recently_active:
        try:
            reply_text = await ai.generate_reply(
                connection, ai_settings, chat_id, message, text, now
            )
            if reply_text and await ai.deliver_reply(
                bot, connection, ai_settings, message, text, reply_text, now
            ):
                return AutoReply("ai", None, reply_text)
        except Exception:
            logger.warning("Сбой ИИ-ответа chat=%s", chat_id, exc_info=True)

    return None
