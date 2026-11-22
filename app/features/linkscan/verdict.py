"""Вердикт проверки: уровень, причины (стабильные коды) и источники. Без сети и aiogram."""

from dataclasses import dataclass

CLEAN, NOTE, SUSPICIOUS, DANGER = 0, 1, 2, 3
ALERT_LEVEL = SUSPICIOUS  # с этого уровня владельцу пишут


@dataclass(frozen=True)
class Verdict:
    level: int = CLEAN
    reasons: tuple[
        str, ...
    ] = ()  # коды: `mismatch`, `phishing`, ... (тексты — в locales)
    sources: tuple[str, ...] = ()  # кто сказал: `local`, `urlhaus`, `safebrowsing`, ...
    ttl: int | None = (
        None  # сколько секунд ответ можно хранить в кэше (None — по умолчанию)
    )

    def merge(self, other: "Verdict") -> "Verdict":
        ttls = [t for t in (self.ttl, other.ttl) if t is not None]
        return Verdict(
            level=max(self.level, other.level),
            reasons=tuple(dict.fromkeys(self.reasons + other.reasons)),
            sources=tuple(dict.fromkeys(self.sources + other.sources)),
            ttl=min(ttls) if ttls else None,
        )

    @property
    def needs_second_opinion(self) -> bool:
        """Подозрение есть, но подтверждения нет: можно потратить дорогой запрос."""
        return NOTE <= self.level < DANGER


def merge_all(verdicts) -> Verdict:
    result = Verdict()
    for verdict in verdicts:
        result = result.merge(verdict)
    return result
