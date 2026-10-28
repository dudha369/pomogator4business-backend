import types

from core import database as db
from handlers.connection import on_business_connection

from .conftest import OWNER_ID


def business_connection(conn_id, enabled=True):
    return types.SimpleNamespace(
        id=conn_id,
        user=types.SimpleNamespace(id=OWNER_ID, full_name="Owner", username="own"),
        user_chat_id=OWNER_ID,
        is_enabled=enabled,
        rights=None,
    )


async def test_reconnect_moves_data_and_prefix(database, bot):
    await on_business_connection(business_connection("old"), bot)
    await db.set_prefix("old", "!")
    await db.disable_module("old", "echo")
    await db.toggle_echo("old", 7)
    await db.save_history("old", 7, 1, False, "привет", 1000)
    await db.log_archive_event("old", 7, 1, "deleted", "привет", None, 1001)
    await db.log_message("old", 7, 1)

    # пользователь отключил и снова подключил бота: приходит НОВЫЙ id
    await on_business_connection(business_connection("old", enabled=False), bot)
    await on_business_connection(business_connection("new"), bot)

    new = await db.get_connection("new")
    assert new["prefix"] == "!"
    assert await db.list_disabled_modules("new") == {"echo"}
    assert await db.is_echo_enabled("new", 7)
    assert await db.get_history_entry("new", 7, 1) is not None
    entries, _ = await db.get_archive_page("new", None, 10)
    assert len(entries) == 1
    # на старом id ничего не осталось
    assert await db.list_disabled_modules("old") == set()
    assert await db.get_history_entry("old", 7, 1) is None


async def test_first_connection_has_nothing_to_move(database, bot):
    await on_business_connection(business_connection("first"), bot)
    assert (await db.get_connection("first"))["prefix"] == "."


async def test_reenabling_same_connection_does_not_touch_data(database, bot):
    await on_business_connection(business_connection("c"), bot)
    await db.disable_module("c", "echo")
    await on_business_connection(business_connection("c", enabled=False), bot)
    await on_business_connection(business_connection("c"), bot)
    assert await db.list_disabled_modules("c") == {"echo"}


async def test_other_owner_data_is_not_moved(database, bot):
    await db.upsert_connection("someone-else", 999, 999, True)
    await db.disable_module("someone-else", "echo")
    await on_business_connection(business_connection("mine"), bot)
    assert await db.list_disabled_modules("someone-else") == {"echo"}
    assert await db.list_disabled_modules("mine") == set()
