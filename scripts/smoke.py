"""Ручная проверка после выкладки. Ничего не пишет, содержимое не печатает.

1. Читает по N последних строк каждой шифруемой таблицы и расшифровывает их слоем vault
   (считает неудачи; `open_column` напрямую — без alert-ов владельцам).
2. Обходит GET-эндпоинты /api/* без параметров с initData администратора (подпись по
   BOT_TOKEN из .env, id — первый из ADMIN_USER_IDS) и ждёт не-5xx.

    uv run python scripts/smoke.py [--rows 20] [--base-url https://...] [--no-api] [--no-vault]

На копии БД: подставьте DB_URL ветки Neon (как в RUNBOOK_release.md), --no-api.
Код возврата 0 — всё в порядке, 1 — что-то сломано."""

import argparse
import asyncio
import hashlib
import hmac
import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlencode

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

SKIP_PARTS = ("/export", "/media", "/avatar", "/dialogs", "/custom-emoji")


def make_init_data(bot_token: str, user_id: int, now: int | None = None) -> str:
    """initData как у мини-приложения: подпись HMAC по токену бота."""
    pairs = {
        "auth_date": str(int(now or time.time())),
        "user": json.dumps({"id": user_id, "first_name": "smoke"}),
    }
    check = "\n".join(f"{k}={v}" for k, v in sorted(pairs.items()))
    secret = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    pairs["hash"] = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    return urlencode(pairs)


def pick_endpoints(openapi: dict) -> list[str]:
    """GET без параметров пути и без обязательных query; тяжёлые и внешние пропускаем."""
    paths = []
    for path, item in sorted(openapi["paths"].items()):
        op = item.get("get")
        if not op or "{" in path or any(part in path for part in SKIP_PARTS):
            continue
        if any(
            p.get("required") and p.get("in") != "header"
            for p in op.get("parameters", [])
        ):
            continue
        paths.append(path)
    return paths


async def check_vault(rows_per_table: int) -> tuple[list[str], int]:
    """(проблемы, число проверенных строк). Расшифровка через те же функции, что в боте."""
    import importlib

    from app.features.vault import service as vault
    from app.features.vault.tables import TABLES

    if not vault.enabled():
        return ["шифрование выключено (DATA_MASTER_KEYS не задан)"], 0
    problems, checked = [], 0
    for table in TABLES.values():
        module, cls = table.model.split(":")
        model = getattr(importlib.import_module(module), cls)
        rows = await model.all().order_by(f"-{table.pk}").limit(rows_per_table).values()
        bad = 0
        for row in rows:
            if row.get("enc_ver") is None:
                continue
            owner = (
                await vault.owner_of(row["connection_id"])
                if table.owner_by == "connection_id"
                else row["owner_id"]
            )
            checked += 1
            for column in table.columns:
                if row.get(column) is None:
                    continue
                try:
                    await vault.open_column(table.name, owner, column, row[column])
                except Exception:
                    bad += 1
                    break
        if bad:
            problems.append(
                f"{table.name}: не расшифровалось строк {bad} из {len(rows)}"
            )
    return problems, checked


def _get(url: str, init_data: str) -> int:
    request = urllib.request.Request(url, headers={"X-Telegram-Init-Data": init_data})
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            return response.status
    except urllib.error.HTTPError as exc:
        return exc.code


async def check_api(base_url: str, init_data: str) -> tuple[list[str], list[str]]:
    from app.main import app

    problems, notes = [], []
    for path in pick_endpoints(app.openapi()):
        try:
            status = await asyncio.to_thread(
                _get, base_url.rstrip("/") + path, init_data
            )
        except Exception as exc:
            problems.append(f"{path}: нет ответа ({type(exc).__name__})")
            continue
        if status >= 500:
            problems.append(f"{path}: {status}")
        elif status >= 400:
            notes.append(f"{path}: {status} (для пустых данных это нормально)")
    return problems, notes


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rows", type=int, default=20)
    parser.add_argument("--base-url", default="")
    parser.add_argument("--no-api", action="store_true")
    parser.add_argument("--no-vault", action="store_true")
    args = parser.parse_args()

    from tortoise import Tortoise

    from app.features.limits.plans import admin_ids
    from app.features.ops import startup
    from app.features.vault import service as vault
    from config import TORTOISE_ORM, settings

    problems: list[str] = []
    await Tortoise.init(config=TORTOISE_ORM)
    try:
        db, repo = await startup.db_version(), startup.repo_version()
        print(f"миграции: БД {db}, код {repo}")
        if db != repo:
            problems.append(f"версии миграций не совпадают: БД {db}, код {repo}")
        if not args.no_vault:
            await vault.startup_check()
            vault_problems, checked = await check_vault(args.rows)
            print(f"vault: проверено строк {checked}")
            problems += vault_problems
    except Exception as exc:
        problems.append(f"{type(exc).__name__}: {exc}")
    finally:
        await Tortoise.close_connections()

    if not args.no_api:
        base = args.base_url or settings.WEBHOOK_BASE_URL
        admins = sorted(admin_ids())
        if not base or not admins:
            problems.append(
                "для проверки API нужны --base-url (или WEBHOOK_BASE_URL) и ADMIN_USER_IDS"
            )
        else:
            init_data = make_init_data(settings.BOT_TOKEN, admins[0])
            api_problems, notes = await check_api(base, init_data)
            problems += api_problems
            for note in notes:
                print("  ·", note)

    if problems:
        print("\nСЛОМАНО:")
        for p in problems:
            print("  ✗", p)
        return 1
    print("\nОК")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
