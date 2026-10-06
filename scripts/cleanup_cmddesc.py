"""Разовая чистка: убирает неиспользуемые ключи "cmddesc.*" из modules/locales/*.py
(их читал старый api/commands.py — он давно заменён на схему cmdmeta.*, но сами
строки остались висеть мёртвым грузом в словарях). Заодно убирает автогенерированный
докстринг первой строкой файла, если он там ещё остался — после переноса на cmdmeta
часть этих файлов правилась руками, и пометка "автоматически сгенерировано" там,
где она сохранилась, больше не соответствует действительности.

Запуск (один раз, из корня backend-репозитория):
    uv run python -m scripts.cleanup_cmddesc
"""

import re
from pathlib import Path

LOCALES_DIR = Path("modules/locales")
CMDDESC_LINE = re.compile(r'^\s*"cmddesc\.[^"]+":\s*".*",?\s*$')
DOCSTRING_LINE = re.compile(
    r'^"""Автоматически сгенерировано scripts/split_locales\.py\."""$'
)


def clean_file(path: Path) -> bool:
    lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    if not lines:
        return False

    changed = False
    start = 0

    if DOCSTRING_LINE.match(lines[0].rstrip("\n")):
        start = 1
        if start < len(lines) and lines[start].strip() == "":
            start += 1
        changed = True

    new_lines = []
    for line in lines[start:]:
        if CMDDESC_LINE.match(line.rstrip("\n")):
            changed = True
            continue
        new_lines.append(line)

    if changed:
        path.write_text("".join(new_lines), encoding="utf-8")
    return changed


def main():
    if not LOCALES_DIR.exists():
        print(
            f"Папка {LOCALES_DIR} не найдена — запускай из корня backend-репозитория."
        )
        return

    changed_files = [
        path.name for path in sorted(LOCALES_DIR.glob("*.py")) if clean_file(path)
    ]

    if changed_files:
        print(f"Почищено {len(changed_files)} файлов:")
        for name in changed_files:
            print(f"  - {name}")
    else:
        print(
            "Нечего чистить — мёртвых cmddesc.* ключей и устаревших докстрингов не найдено."
        )

    print("\nПроверь git diff перед коммитом.")


if __name__ == "__main__":
    main()
