"""Статистика переписки: активность по дням, топ собеседников, скорость ответа.

Чистые функции от уже загруженных строк истории — без обращений к БД."""

import datetime
import statistics

MAX_REPLY_GAP_SECONDS = 24 * 3600  # ответ позже суток уже не считаем «скоростью ответа»


def local_date(ts: int, offset_minutes: int) -> str:
    moment = datetime.datetime.fromtimestamp(
        ts + offset_minutes * 60, datetime.timezone.utc
    )
    return moment.strftime("%Y-%m-%d")


def daily_activity(rows, now: int, offset_minutes: int, days: int):
    """[{date, incoming, outgoing}] за последние `days` суток (включая сегодня),
    дни без сообщений заполнены нулями."""
    today = datetime.datetime.fromtimestamp(
        now + offset_minutes * 60, datetime.timezone.utc
    ).date()
    buckets = {
        (today - datetime.timedelta(days=i)).isoformat(): {"incoming": 0, "outgoing": 0}
        for i in range(days - 1, -1, -1)
    }
    for row in rows:
        bucket = buckets.get(local_date(row["created_at"], offset_minutes))
        if bucket is not None:
            bucket["outgoing" if row["is_owner"] else "incoming"] += 1
    return [{"date": date, **counts} for date, counts in buckets.items()]


def top_chats(rows, limit: int = 5):
    totals = {}
    for row in rows:
        entry = totals.setdefault(
            row["chat_id"], {"chat_id": row["chat_id"], "incoming": 0, "outgoing": 0}
        )
        entry["outgoing" if row["is_owner"] else "incoming"] += 1
    ranked = sorted(
        totals.values(), key=lambda e: (-(e["incoming"] + e["outgoing"]), e["chat_id"])
    )
    return ranked[:limit]


def reply_times(rows):
    """Секунды между первым неотвеченным входящим и ответом владельца,
    по каждому чату отдельно. rows — по возрастанию времени."""
    pending = {}  # chat_id -> время первого неотвеченного входящего
    samples = []
    for row in sorted(rows, key=lambda r: (r["created_at"], r.get("message_id", 0))):
        chat = row["chat_id"]
        if row["is_owner"]:
            started = pending.pop(chat, None)
            if started is not None:
                gap = row["created_at"] - started
                if 0 <= gap <= MAX_REPLY_GAP_SECONDS:
                    samples.append(gap)
        else:
            pending.setdefault(chat, row["created_at"])
    return samples


def reply_summary(samples):
    if not samples:
        return {"median_seconds": None, "p90_seconds": None, "samples": 0}
    ordered = sorted(samples)
    p90 = ordered[min(len(ordered) - 1, int(len(ordered) * 0.9))]
    return {
        "median_seconds": int(statistics.median(ordered)),
        "p90_seconds": int(p90),
        "samples": len(ordered),
    }
