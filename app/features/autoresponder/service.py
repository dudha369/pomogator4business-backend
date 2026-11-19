"""Автоответчик: приветствие новому собеседнику, режим «нет на месте» по
расписанию, ответы по ключевым словам, авто-прочтение.

Структура: чистые функции (`in_away_window`, `pick_keyword`, `render`,
`build_candidates`) без обращений к БД/Telegram — их легко тестировать, —
и один оркестратор `handle_incoming`, который собирает факты, выбирает ответ
и отправляет. На каждое входящее сообщение уходит не больше ОДНОГО автоответа
(приоритет: ключевое слово → «нет на месте» → приветствие).

ИИ (app/features/ai/service.py) подключается последним: если не сработало ни одно правило.

Защита от спама и циклов:
- не отвечаем ботам и не-личным чатам;
- не отвечаем на сообщения-команды (начинаются с префикса);
- не отвечаем, если владелец сам писал в чат в последние 10 минут (для
  «нет на месте» — он явно на связи);
- кулдауны хранятся в БД (autoresponder_log), а не в памяти — переживают
  перезапуск: приветствие — один раз на собеседника, «нет на месте» — раз в
  6 часов, ключевое слово — раз в 5 минут на слово.
"""

from dataclasses import dataclass

AWAY_COOLDOWN_SECONDS = 6 * 3600
KEYWORD_COOLDOWN_SECONDS = 300
OWNER_ACTIVE_WINDOW_SECONDS = 600
MAX_REPLY_LENGTH = 4096  # лимит Telegram на длину сообщения


NO_SETTINGS = {
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
