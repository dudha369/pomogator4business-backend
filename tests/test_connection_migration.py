import types

from app.features.archive.queries import get_archive_page, log_archive_event
from db.models.connection import get_connection, set_prefix, upsert_connection
from db.models.echo import is_echo_enabled, toggle_echo
from db.models.message_history import get_history_entry, save_history
from db.models.message_log import log_message
from db.models.module_settings import disable_module, list_disabled_modules
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
    await set_prefix("old", "!")
    await disable_module("old", "echo")
    await toggle_echo("old", 7)
    await save_history("old", 7, 1, False, "привет", 1000)
    await log_archive_event("old", 7, 1, "deleted", "привет", None, 1001)
    await log_message("old", 7, 1)

    # пользователь отключил и снова подключил бота: приходит НОВЫЙ id
    await on_business_connection(business_connection("old", enabled=False), bot)
    await on_business_connection(business_connection("new"), bot)

    new = await get_connection("new")
    assert new["prefix"] == "!"
    assert await list_disabled_modules("new") == {"echo"}
    assert await is_echo_enabled("new", 7)
    assert await get_history_entry("new", 7, 1) is not None
    entries, _ = await get_archive_page("new", None, 10)
    assert len(entries) == 1
    # на старом id ничего не осталось
    assert await list_disabled_modules("old") == set()
    assert await get_history_entry("old", 7, 1) is None


async def test_first_connection_has_nothing_to_move(database, bot):
    await on_business_connection(business_connection("first"), bot)
    assert (await get_connection("first"))["prefix"] == "."


async def test_reenabling_same_connection_does_not_touch_data(database, bot):
    await on_business_connection(business_connection("c"), bot)
    await disable_module("c", "echo")
    await on_business_connection(business_connection("c", enabled=False), bot)
    await on_business_connection(business_connection("c"), bot)
    assert await list_disabled_modules("c") == {"echo"}


async def test_other_owner_data_is_not_moved(database, bot):
    await upsert_connection("someone-else", 999, 999, True)
    await disable_module("someone-else", "echo")
    await on_business_connection(business_connection("mine"), bot)
    assert await list_disabled_modules("someone-else") == {"echo"}
    assert await list_disabled_modules("mine") == set()
