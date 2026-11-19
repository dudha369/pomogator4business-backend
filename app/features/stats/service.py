"""Статистика переписки: активность по дням, топ собеседников, скорость ответа.

Чистые функции от уже загруженных строк истории — без обращений к БД."""

import datetime
import statistics

MAX_REPLY_GAP_SECONDS = 24 * 3600  # ответ позже суток уже не считаем «скоростью ответа»


def local_date(ts: int, offset_minutes: int) -> str:
    moment = datetime.datetime.fromtimestamp(ts + offset_minutes * 60, datetime.UTC)
    return moment.strftime("%Y-%m-%d")


def daily_from_counts(counts, now: int, offset_minutes: int, days: int):
    """counts: [{day, is_owner, n}] (day — число суток с 1970-01-01 по локальному времени).
    Возвращает [{date, incoming, outgoing}] за `days` суток, пустые дни — нули."""
    today = datetime.datetime.fromtimestamp(
        now + offset_minutes * 60, datetime.UTC
    ).date()
    buckets = {
        (today - datetime.timedelta(days=i)).isoformat(): {"incoming": 0, "outgoing": 0}
        for i in range(days - 1, -1, -1)
    }
    epoch = datetime.date(1970, 1, 1)
    for row in counts:
        date = (epoch + datetime.timedelta(days=int(row["day"]))).isoformat()
        bucket = buckets.get(date)
        if bucket is not None:
            bucket["outgoing" if row["is_owner"] else "incoming"] += int(row["n"])
    return [{"date": date, **c} for date, c in buckets.items()]


def daily_activity(rows, now: int, offset_minutes: int, days: int):
    """То же по «сырым» строкам истории (по одной на сообщение)."""
    counts = {}
    for row in rows:
        day = (row["created_at"] + offset_minutes * 60) // 86400
        key = (day, bool(row["is_owner"]))
        counts[key] = counts.get(key, 0) + 1
    return daily_from_counts(
        [{"day": d, "is_owner": o, "n": n} for (d, o), n in counts.items()],
        now,
        offset_minutes,
        days,
    )


def top_from_counts(counts, limit: int = 5):
    """counts: [{chat_id, is_owner, n}] -> топ собеседников."""
    totals = {}
    for row in counts:
        entry = totals.setdefault(
            row["chat_id"], {"chat_id": row["chat_id"], "incoming": 0, "outgoing": 0}
        )
        entry["outgoing" if row["is_owner"] else "incoming"] += int(row["n"])
    ranked = sorted(
        totals.values(), key=lambda e: (-(e["incoming"] + e["outgoing"]), e["chat_id"])
    )
    return ranked[:limit]


def top_chats(rows, limit: int = 5):
    return top_from_counts(
        [{"chat_id": r["chat_id"], "is_owner": r["is_owner"], "n": 1} for r in rows],
        limit,
    )


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
