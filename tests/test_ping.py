from modules.ping import cmd_ping
from core.context import CommandContext

from .conftest import make_message, OWNER_ID


async def test_ping_endpoint_is_public_and_not_cached(client):
    r = await client.get("/api/ping")
    assert r.status_code == 200 and r.json()["ok"] is True
    assert r.headers["cache-control"] == "no-store"


async def test_deep_ping_requires_auth_and_reports_health(client, api_bot):
    assert (await client.get("/api/ping/deep")).status_code in (401, 422)
    body = (await client.get("/api/ping/deep", headers=client.owner)).json()
    assert body["telegram_ms"] is not None and body["db_ms"] is not None
    assert body["uptime_seconds"] >= 0


async def test_ping_command_replies_with_pong(connection, bot):
    ctx = CommandContext(
        bot=bot,
        message=make_message(".ping", from_id=OWNER_ID),
        connection=connection,
        args="",
        locale="ru",
        dm=True,
    )
    await cmd_ping(ctx)
    assert "pong" in bot.sent[-1]["text"]
