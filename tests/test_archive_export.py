import csv
import io
import json
import re

from core import archive_export as ex
from core import database as db

from .conftest import CONNECTION_ID

NOW = 1_800_000_000


def entry(log_id, chat_id, event, old, new=None, ts=NOW, media=None):
    return {
        "log_id": log_id,
        "chat_id": chat_id,
        "message_id": log_id,
        "event": event,
        "old_text": old,
        "new_text": new,
        "created_at": ts,
        "media_type": media,
    }


ENTRIES = [
    entry(
        1, 7, "deleted", "<script>alert(1)</script> привет", ts=NOW - 300, media="photo"
    ),
    entry(2, 8, "edited", '=HYPERLINK("evil")', "новый", ts=NOW - 200),
    entry(3, 7, "edited", "было", "стало", ts=NOW - 100, media="video"),
]
NAMES = {7: "Аня"}


def test_html_escapes_and_groups():
    doc = ex.build_html(
        ENTRIES, NAMES, 180, "ru", NOW, photos={1: b"JPEGDATA"}
    ).decode()
    assert "<script>alert" not in doc and "&lt;script&gt;" in doc
    assert re.findall(r"<h2>(.*?)</h2>", doc) == ["Аня", "Чат 8"]
    assert "data:image/jpeg;base64," in doc
    assert "видео — медиа не включено" in doc


def test_csv_neutralises_formulas_and_keeps_cyrillic():
    raw = ex.build_csv(ENTRIES, NAMES, 180, "ru")
    rows = list(csv.reader(io.StringIO(raw.decode("utf-8-sig"))))
    assert rows[0][0] == "date" and len(rows) == 4
    assert any(r[4].startswith("'=") for r in rows)
    assert any("Аня" in r[2] for r in rows)


def test_json_has_local_time():
    data = json.loads(ex.build_json(ENTRIES, NAMES, 180, "ru", NOW))
    assert data["count"] == 3 and data["timezone_offset_minutes"] == 180
    assert data["entries"][0]["created_at_local"] == ex.format_ts(NOW - 300, 180)


def test_timezone_formatting():
    assert ex.format_ts(0, 180) == "1970-01-01 03:00:00"
    assert ex.format_ts(0, -300) == "1969-12-31 19:00:00"


async def seed():
    await db.save_history(
        CONNECTION_ID,
        7,
        70,
        False,
        "x",
        NOW - 500,
        media_type="photo",
        media_data=b"\xff\xd8J",
    )
    await db.log_archive_event(
        CONNECTION_ID, 7, 70, "deleted", "<b>hi</b>", None, NOW - 300
    )
    await db.log_archive_event(CONNECTION_ID, 8, 80, "edited", "a", "b", NOW - 200)


async def test_export_endpoint_sends_document(client, api_bot):
    await seed()
    r = await client.post(
        "/api/archive/export",
        headers=client.owner,
        json={"format": "html", "include_media": True},
    )
    assert r.status_code == 200
    assert r.json()["entries"] == 2 and r.json()["photos_embedded"] == 1
    doc = api_bot.documents[0]
    assert doc["chat_id"] == 42 and doc["document"].filename.endswith(".html")
    assert b"&lt;b&gt;hi" in doc["document"].data


async def test_export_filters_and_errors(client, api_bot):
    await seed()
    h = client.owner
    r = await client.post(
        "/api/archive/export", headers=h, json={"format": "json", "event": "edited"}
    )
    assert r.json()["entries"] == 1
    assert (
        await client.post("/api/archive/export", headers=h, json={"chat_id": 999})
    ).status_code == 404
    assert (
        await client.post("/api/archive/export", headers=h, json={"format": "xml"})
    ).status_code == 422
