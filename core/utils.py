import re

_UNITS = {"s": 1, "m": 60, "h": 3600, "d": 86400}


def parse_duration(raw: str):
    match = re.fullmatch(r"(\d+)([smhd])", raw.strip().lower())
    if not match:
        return None
    value, unit = match.groups()
    return int(value) * _UNITS[unit]


def parse_duration_loose(raw: str):
    raw = raw.strip().lower()
    if raw.isdigit():
        return int(raw)
    return parse_duration(raw)


def log_suppressed(where: str, benign: bool = False) -> None:
    """Вызывается из `except Exception:` вместо молчаливого `pass`.

    benign=True — ожидаемые сбои (сообщение уже удалено, «not modified»):
    пишутся на уровне DEBUG. Остальные — WARNING с трассировкой."""
    import logging

    logging.getLogger("bot.suppressed").log(
        logging.DEBUG if benign else logging.WARNING,
        "Подавлена ошибка: %s",
        where,
        exc_info=True,
    )
