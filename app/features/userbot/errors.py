"""Исключения слоя юзербота. Адаптер переводит в них ошибки Telethon, остальной код
про Telethon не знает."""


class UserbotError(Exception):
    pass


class PasswordNeeded(UserbotError):
    """Включён облачный пароль (2FA)."""


class PasswordInvalid(UserbotError):
    pass


class SessionRevoked(UserbotError):
    """Telegram завершил сеанс (или аккаунт удалён/заблокирован): нужен новый вход."""


class FloodWait(UserbotError):
    def __init__(self, seconds: int):
        super().__init__(f"flood wait {seconds}s")
        self.seconds = seconds
