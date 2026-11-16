"""Пишет OpenAPI-схему REST в generated/openapi.json (вход для openapi-typescript).

uv run python scripts/export_openapi.py
npx openapi-typescript generated/openapi.json -o generated/api-types.ts
"""

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
# схема не зависит от значений; заглушки нужны только чтобы собрался Settings
os.environ.setdefault("BOT_TOKEN", "123456:SCHEMA")
os.environ.setdefault("DB_URL", "sqlite://:memory:")

from app.main import app  # noqa: E402

OPENAPI_PATH = ROOT / "generated" / "openapi.json"


def render() -> str:
    return (
        json.dumps(app.openapi(), ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    )


if __name__ == "__main__":
    OPENAPI_PATH.write_text(render(), encoding="utf-8")
    print(f"written {OPENAPI_PATH}")
