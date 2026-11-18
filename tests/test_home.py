"""GET /api/home: сводка главной одним запросом."""

import time

from app.features.archive.queries import log_archive_event
from app.features.history.service import save_history

from .conftest import CONNECTION_ID, init_data_headers

NOW = int(time.time())


async def test_home_requires_auth(client):
    r = await client.get("/api/home")
    assert r.status_code in (401, 422)


async def test_home_matches_the_endpoints_it_replaces(client):
    h = client.owner
    await save_history(CONNECTION_ID, 7, 1, False, "a", NOW - 60)
    await save_history(CONNECTION_ID, 7, 2, True, "b", NOW - 30)
    for i in range(5):
        await log_archive_event(CONNECTION_ID, 7, 70 + i, "deleted", "t", None, NOW - i)

    home = (await client.get("/api/home", headers=h)).json()
    settings = (await client.get("/api/settings", headers=h)).json()
    commands = (await client.get("/api/commands", headers=h)).json()
    stats = (await client.get("/api/stats", headers=h)).json()
    account = (await client.get("/api/account", headers=h)).json()
    archive = (await client.get("/api/archive?limit=3", headers=h)).json()

    assert home["connected"] is True
    assert home["owner_name"] == account["connection"]["owner_name"]
    assert home["owner_username"] == account["connection"]["owner_username"]
    assert home["mirror_connected"] == account["mirror"]["connected"]
    assert home["commands_total"] == len(commands["commands"]) > 0
    assert home["modules_total"] == len(settings["modules"])
    assert home["modules_enabled"] == sum(m["enabled"] for m in settings["modules"])
    assert home["stats"] == stats
    assert home["recent_archive"] == archive["entries"]
    assert len(home["recent_archive"]) == 3


async def test_home_emoji_status_is_granted_and_enabled(client):
    home = (await client.get("/api/home", headers=client.owner)).json()
    account = (await client.get("/api/account", headers=client.owner)).json()
    emoji = account["emoji_status"]
    assert home["emoji_status_granted"] == emoji["granted"]
    assert home["emoji_status_enabled"] == (emoji["granted"] and emoji["enabled"])


async def test_home_counts_disabled_modules(client):
    h = client.owner
    module = (await client.get("/api/settings", headers=h)).json()["modules"][0]["name"]
    await client.post(
        "/api/settings/module", headers=h, json={"module": module, "enabled": False}
    )
    home = (await client.get("/api/home", headers=h)).json()
    assert home["modules_enabled"] == home["modules_total"] - 1


async def test_home_without_connection_is_not_an_error(client):
    """Пользователь без бизнес-подключения: 200 и «бот не подключён», а не 404."""
    r = await client.get("/api/home", headers=init_data_headers(user_id=999))
    assert r.status_code == 200
    body = r.json()
    assert body["connected"] is False
    assert body["owner_name"] is None
    assert body["stats"] is None
    assert body["recent_archive"] == []
    assert body["modules_enabled"] == body["modules_total"] > 0


async def test_home_survives_broken_optional_parts(client, monkeypatch):
    async def boom(*_args, **_kwargs):
        raise RuntimeError("db down")

    monkeypatch.setattr("app.features.miniapp.api.home.get_stats", boom)
    r = await client.get("/api/home", headers=client.owner)
    assert r.status_code == 200
    body = r.json()
    assert body["connected"] is True
    assert body["stats"] is None and body["recent_archive"] == []


async def test_keyword_replies_do_not_expose_owner_id(client):
    h = client.owner
    await client.post(
        "/api/autoresponder/keywords",
        headers=h,
        json={"keyword": "цена", "reply_text": "100"},
    )
    keywords = (await client.get("/api/autoresponder", headers=h)).json()["keywords"]
    assert [set(k) for k in keywords] == [{"id", "keyword", "reply_text"}]
    exported = (await client.get("/api/backup/export", headers=h)).json()["keywords"]
    assert all("owner_id" not in k for k in exported)
