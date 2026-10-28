import time

from core import database as db

from .conftest import CONNECTION_ID, OWNER_ID

NOW = int(time.time())


async def test_requires_auth(client):
    r = await client.get("/api/stats")
    assert r.status_code in (401, 422)


# ----------------------------- автоответчик ---------------------------------


async def test_autoresponder_validation(client):
    h = client.owner
    r = await client.post(
        "/api/autoresponder", headers=h, json={"greeting_enabled": True}
    )
    assert r.status_code == 422  # нельзя включить без текста
    r = await client.post(
        "/api/autoresponder",
        headers=h,
        json={"greeting_enabled": True, "greeting_text": "Привет"},
    )
    assert r.status_code == 200 and r.json()["greeting_enabled"] is True
    assert (
        await client.post(
            "/api/autoresponder", headers=h, json={"away_start_minutes": 2000}
        )
    ).status_code == 422
    kw = {"keyword": "  ", "reply_text": "x"}
    assert (
        await client.post("/api/autoresponder/keywords", headers=h, json=kw)
    ).status_code == 422


async def test_autoresponder_can_clear_schedule(client):
    h = client.owner
    await client.post(
        "/api/autoresponder",
        headers=h,
        json={"away_start_minutes": 60, "away_end_minutes": 120},
    )
    r = await client.post(
        "/api/autoresponder", headers=h, json={"away_start_minutes": None}
    )
    assert (
        r.json()["away_start_minutes"] is None and r.json()["away_end_minutes"] == 120
    )


async def test_keywords_are_normalised_and_deletable(client):
    h = client.owner
    await client.post(
        "/api/autoresponder/keywords",
        headers=h,
        json={"keyword": " Цена ", "reply_text": "100"},
    )
    assert [
        k["keyword"]
        for k in (await client.get("/api/autoresponder", headers=h)).json()["keywords"]
    ] == ["цена"]
    await client.delete("/api/autoresponder/keywords/цена", headers=h)
    assert (await client.get("/api/autoresponder", headers=h)).json()["keywords"] == []


# -------------------------------- алиасы ------------------------------------


async def test_alias_lifecycle_and_validation(client):
    h = client.owner
    r = await client.post(
        "/api/aliases", headers=h, json={"command": "ping", "alias": ".П"}
    )
    assert r.json() == {"alias": "п", "command": "ping"}
    assert (
        await client.post(
            "/api/aliases", headers=h, json={"command": "ping", "alias": "п"}
        )
    ).status_code == 409
    assert (
        await client.post(
            "/api/aliases", headers=h, json={"command": "ping", "alias": "ping"}
        )
    ).status_code == 409
    assert (
        await client.post(
            "/api/aliases", headers=h, json={"command": "ping", "alias": "a b"}
        )
    ).status_code == 400
    assert (
        await client.post(
            "/api/aliases", headers=h, json={"command": "nope", "alias": "zz"}
        )
    ).status_code == 404
    assert (await client.delete("/api/aliases/%D0%BF", headers=h)).status_code == 200
    assert (await client.delete("/api/aliases/%D0%BF", headers=h)).status_code == 404


# ------------------------- статистика, чаты, избранное ----------------------


async def test_stats_counts(client):
    await db.save_history(CONNECTION_ID, 7, 1, False, "a", NOW - 60)
    await db.save_history(CONNECTION_ID, 7, 2, True, "b", NOW - 30)
    await db.save_history(CONNECTION_ID, 7, 3, False, "old", NOW - 3 * 86400)
    body = (await client.get("/api/stats", headers=client.owner)).json()
    assert body["week"] == {"total": 3, "incoming": 2}
    assert body["today"]["total"] <= 2


async def test_chats_favorites_and_readall(client, api_bot):
    h = client.owner
    await db.save_history(CONNECTION_ID, 7, 71, False, "a", NOW - 1800)
    await db.save_history(CONNECTION_ID, 8, 80, False, "b", NOW - 30 * 3600)
    await client.post(
        "/api/favorites", headers=h, json={"chat_id": 7, "favorite": True}
    )

    chats = {
        c["chat_id"]: c
        for c in (await client.get("/api/chats", headers=h)).json()["chats"]
    }
    assert chats[7]["favorite"] is True and chats[8]["favorite"] is False

    dry = await client.post(
        "/api/readall", headers=h, json={"dry_run": True, "exclude_favorites": True}
    )
    assert dry.json()["matched"] == 1 and api_bot.reads == []

    done = await client.post("/api/readall", headers=h, json={"older_hours": 24})
    assert done.json() == {"matched": 1, "done": 1, "failed": 0}
    assert api_bot.reads[0]["chat_id"] == 8 and api_bot.reads[0]["message_id"] == 80
    assert (
        await client.post("/api/readall", headers=h, json={"last_hours": 0})
    ).status_code == 422


# -------------------------------- архив -------------------------------------


async def test_archive_sort_pagination_media_and_filters(client):
    h = client.owner
    await db.save_history(
        CONNECTION_ID,
        7,
        70,
        False,
        "x",
        NOW - 500,
        media_type="photo",
        media_data=b"JPEG",
    )
    for i, ts in enumerate((NOW - 300, NOW - 200, NOW - 100)):
        await db.log_archive_event(
            CONNECTION_ID, 7, 70 + i, "deleted" if i < 2 else "edited", "t", None, ts
        )

    asc = (await client.get("/api/archive?sort=asc&limit=2", headers=h)).json()
    assert [e["log_id"] for e in asc["entries"]] == [1, 2] and asc["has_more"]
    nxt = (
        await client.get(
            f"/api/archive?sort=asc&limit=2&before_id={asc['next_before_id']}",
            headers=h,
        )
    ).json()
    assert [e["log_id"] for e in nxt["entries"]] == [3]
    assert (
        asc["entries"][0]["media_type"] == "photo"
        and asc["entries"][1]["media_type"] is None
    )

    assert (
        len(
            (await client.get("/api/archive?event=edited", headers=h)).json()["entries"]
        )
        == 1
    )
    assert (
        len(
            (await client.get(f"/api/archive?date_from={NOW - 250}", headers=h)).json()[
                "entries"
            ]
        )
        == 2
    )

    media = await client.get("/api/archive/1/media", headers=h)
    assert (
        media.status_code == 200
        and media.content == b"JPEG"
        and media.headers["content-type"] == "image/jpeg"
    )
    assert (await client.get("/api/archive/2/media", headers=h)).status_code == 404
    assert (await client.get("/api/archive/999/media", headers=h)).status_code == 404


async def test_archive_media_is_private_to_owner(client, database):
    await db.upsert_connection("other", 777, 777, True)
    await db.save_history(
        "other", 1, 1, False, "x", NOW, media_type="photo", media_data=b"SECRET"
    )
    await db.log_archive_event("other", 1, 1, "deleted", "x", None, NOW)
    # чужая запись архива недоступна владельцу другого подключения
    assert (
        await client.get("/api/archive/1/media", headers=client.owner)
    ).status_code == 404


async def test_commands_expose_scope(client):
    cmds = {
        c["name"]: c for c in (await client.get("/api/commands")).json()["commands"]
    }
    assert cmds["ping"]["scope"] == "both" and cmds["readall"]["scope"] == "both"
    assert cmds["fav"]["scope"] == "chat"
