"""Чистка базы: reply_gaps в SQL, retention через реестр фич, очистка старых данных, индексы."""

import random
from pathlib import Path

import pytest

from app.features import FEATURES, feature_module
from app.features.history.models import MessageHistory, MessageLog
from app.features.history.service import (
    expire_message_log,
    log_message,
    reply_gaps,
    save_history,
    scrub_raw_json,
)
from app.platform import retention
from config import settings

from .conftest import CONNECTION_ID, NOW

DAY = 86400


def oracle_reply_times(rows):
    """Прежний алгоритм на Python — эталон для SQL-версии."""
    pending, samples = {}, []
    for row in sorted(rows, key=lambda r: (r["created_at"], r["message_id"])):
        chat = row["chat_id"]
        if row["is_owner"]:
            started = pending.pop(chat, None)
            if started is not None and 0 <= row["created_at"] - started <= DAY:
                samples.append(row["created_at"] - started)
        else:
            pending.setdefault(chat, row["created_at"])
    return samples


async def _seed(rows):
    for chat, owner, ts, mid in rows:
        await save_history(CONNECTION_ID, chat, mid, owner, "t", ts)


async def test_reply_gaps_handbook_case(connection):
    await _seed(
        [
            (1, False, 100, 1),
            (1, False, 130, 2),
            (1, True, 400, 3),  # 300 с от ПЕРВОГО неотвеченного
            (2, False, 200, 4),
            (2, True, 260, 5),  # 60 с
            (3, True, 500, 6),  # ответ без входящего
            (1, False, 1000, 7),
            (1, True, 1000 + 25 * 3600, 8),  # дольше суток
        ]
    )
    assert sorted(await reply_gaps(CONNECTION_ID, 0)) == [60, 300]


async def test_reply_gaps_respects_window_and_connection(connection):
    await _seed([(1, False, 100, 1), (1, True, 200, 2), (1, False, 500, 3)])
    await _seed([(1, True, 600, 4)])
    assert sorted(await reply_gaps(CONNECTION_ID, 0)) == [100, 100]
    assert await reply_gaps(CONNECTION_ID, 300) == [100]  # окно режет серию
    assert await reply_gaps("other", 0) == []


@pytest.mark.parametrize("seed", range(5))
async def test_reply_gaps_match_python_oracle(connection, seed):
    rnd = random.Random(seed)
    rows = []
    for mid in range(1, 301):
        rows.append(
            (
                rnd.randint(1, 5),
                rnd.random() < 0.4,
                1_000_000 + rnd.randint(0, 3 * DAY),  # есть совпадения по времени
                mid,
            )
        )
    await _seed(rows)
    expected = oracle_reply_times(
        [
            {"chat_id": c, "is_owner": o, "created_at": t, "message_id": m}
            for c, o, t, m in rows
        ]
    )
    assert sorted(await reply_gaps(CONNECTION_ID, 0)) == sorted(expected)


# ------------------------------- очистка данных -----------------------------


async def test_scrub_raw_json_only_for_text_and_files(connection):
    snap = {"kind": "text", "raw_json": {"a": 1}}
    await save_history(CONNECTION_ID, 1, 1, False, "t", NOW, snapshot=snap)
    await save_history(
        CONNECTION_ID, 1, 2, False, None, NOW, snapshot={**snap, "kind": "photo"}
    )
    await save_history(
        CONNECTION_ID, 1, 3, False, None, NOW, snapshot={**snap, "kind": "poll"}
    )
    assert await scrub_raw_json(10) == 2
    assert await scrub_raw_json(10) == 0
    left = await MessageHistory.filter(raw_json__not_isnull=True).values_list(
        "message_id", flat=True
    )
    assert list(left) == [3]  # экзотический тип сохранил raw_json


async def test_scrub_raw_json_task_runs_in_batches(connection, monkeypatch):
    for mid in range(5):
        await save_history(
            CONNECTION_ID, 1, mid, False, "t", NOW, snapshot={"kind": "text"}
        )
    await MessageHistory.all().update(raw_json={"old": True})  # «старые» строки
    monkeypatch.setattr(settings, "RAW_JSON_SCRUB_BATCH", 2)
    stats = await retention.run_retention_once(NOW)
    assert stats["raw_json_scrubbed"] == 5
    monkeypatch.setattr(settings, "RAW_JSON_SCRUB_BATCH", 0)
    assert "raw_json_scrubbed" not in await retention.run_retention_once(NOW)


async def test_message_log_expires_by_age_and_keeps_legacy_rows(connection):
    await log_message(CONNECTION_ID, 1, 1)
    await log_message(CONNECTION_ID, 1, 2)
    await MessageLog.filter(message_id=1).update(created_at=NOW - 40 * DAY)
    await MessageLog.filter(message_id=2).update(created_at=NOW - DAY)
    await MessageLog.create(connection_id=CONNECTION_ID, chat_id=1, message_id=3)
    assert await expire_message_log(NOW - 30 * DAY) == 1
    left = sorted(await MessageLog.all().values_list("message_id", flat=True))
    assert left == [2, 3]  # свежая и запись без времени остались


async def test_message_log_retention_can_be_disabled(connection, monkeypatch):
    monkeypatch.setattr(settings, "MESSAGE_LOG_RETENTION_DAYS", 0)
    assert "message_log_expired" not in await retention.run_retention_once(NOW)


# --------------------------------- реестр -----------------------------------


async def test_registry_collects_feature_tasks(database):
    names = set(retention.registered_tasks())
    assert {
        "media_expired",
        "history_purged",
        "message_log_expired",
        "message_log_trimmed",
        "raw_json_scrubbed",
        "archive_media_expired",
        "archive_purged",
        "autoresponder_log_purged",
        "ai_drafts_purged",
    } <= names


async def test_failing_task_does_not_stop_others(database, monkeypatch):
    async def boom(now):
        raise RuntimeError("сбой")

    monkeypatch.setitem(retention._TASKS, "boom", boom)
    stats = await retention.run_retention_once(NOW)
    assert "boom" not in stats and "history_purged" in stats


def test_duplicate_task_name_is_rejected():
    with pytest.raises(ValueError):
        retention.retention_task("history_purged")(lambda now: None)


def test_platform_retention_has_no_feature_queries():
    """Платформа не знает, что чистят фичи: только реестр и FEATURES."""
    text = Path(retention.__file__).read_text(encoding="utf-8")
    assert "queries" not in text and "features.history" not in text


def test_retention_modules_live_in_features():
    owners = [f for f in FEATURES if feature_module(f, "retention")]
    assert set(owners) == {
        "ai",
        "archive",
        "autoresponder",
        "history",
        "limits",
        "linkscan",
        "ops",
        "vault",
    }
