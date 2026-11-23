"""Единый список шифруемых колонок. Чистые данные: моделей не импортирует (иначе цикл с
фичами, чьи `service.py` вызывают vault)."""

from dataclasses import dataclass

TEXT, JSON, BIN = "text", "json", "bin"


@dataclass(frozen=True)
class Table:
    name: str
    model: str  # "модуль:Класс" — импортируется лениво (бэкфилл)
    pk: str
    columns: dict[str, str]  # колонка -> TEXT | JSON | BIN
    owner_by: str  # "connection_id" (владелец — через подключение) | "owner_id"


TABLES: dict[str, Table] = {
    t.name: t
    for t in (
        Table(
            "message_history",
            "app.features.history.models:MessageHistory",
            "id",
            {
                "text": TEXT,
                "entities": JSON,
                "payload": JSON,
                "forward": JSON,
                "raw_json": JSON,
                "transcript": TEXT,
                "media_data": BIN,
                "media_name": TEXT,
            },
            "connection_id",
        ),
        Table(
            "archive_log",
            "app.features.archive.models:ArchiveLog",
            "log_id",
            {
                "old_text": TEXT,
                "new_text": TEXT,
                "old_snapshot": JSON,
                "new_snapshot": JSON,
                "media_data": BIN,
                "media_name": TEXT,
            },
            "connection_id",
        ),
        Table(
            "ai_drafts",
            "app.features.ai.models:AiDraft",
            "id",
            {"text": TEXT},
            "owner_id",
        ),
        Table(
            "alerts",
            "app.features.alerts.models:Alert",
            "id",
            {"details": JSON},
            "owner_id",
        ),
        Table(
            "scheduled_tasks",
            "app.features.scheduled.models:ScheduledTask",
            "id",
            {"text": TEXT},
            "connection_id",
        ),
        Table(
            "userbot_sessions",
            "app.features.userbot.models:UserbotSession",
            "owner_id",
            {"session": TEXT},
            "owner_id",
        ),
    )
}
