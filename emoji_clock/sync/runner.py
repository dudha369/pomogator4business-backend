"""Синхронизация: приводит паки в Telegram и таблицу clock_emojis к стилям из кода.

Для каждого стиля:
  1. смотрит, из какой ревизии дизайна собраны паки, которые сейчас в БД;
  2. если они устарели (или их нет) — собирает НОВЫЕ паки (имя содержит ревизию),
     не трогая старые; все паки стиля грузятся параллельно;
  3. когда весь комплект готов — одной транзакцией переключает БД на него
     (у пользователей нет «пустых» минут);
  4. через delete_delay секунд (пока планировщик переключит всех) удаляет
     старый комплект целиком.
Прерванную сборку можно просто запустить заново: готовое не перезагружается.
"""

import asyncio
import time
from dataclasses import dataclass

from emoji_clock.style import pack_revision
from emoji_clock.sync.builder import build_pack, emoji_rows
from emoji_clock.sync.telegram import Telegram

DEFAULT_OWNER_ID = 1218892156  # пользователь-владелец наборов (как и раньше)
DEFAULT_CONCURRENCY = 8  # паков одновременно
DEFAULT_DELETE_DELAY = 90  # сек до удаления старых паков после переключения
TICK_SECONDS = 20  # как часто печатать общий прогресс


@dataclass
class Plan:
    style: object
    live: list  # строки ClockPack, которые сейчас в БД
    action: str  # "skip" | "build"
    reason: str


def make_plan(style, live_rows):
    if not live_rows:
        return Plan(style, [], "build", "паков ещё нет")
    revisions = {pack_revision(row["pack_name"]) for row in live_rows}
    complete = len(live_rows) == style.pack_count and all(
        r["completed"] for r in live_rows
    )
    if complete and revisions == {style.revision}:
        return Plan(style, live_rows, "skip", f"актуален (ревизия {style.revision})")
    if not complete:
        return Plan(style, live_rows, "build", "комплект неполный")
    old = ", ".join(str(r) for r in sorted(revisions))
    return Plan(style, live_rows, "build", f"ревизия {old} -> {style.revision}")


class Progress:
    def __init__(self, total):
        self.total = total
        self.done = 0
        self.started = time.monotonic()

    def add(self, n):
        self.done += n

    def line(self):
        elapsed = time.monotonic() - self.started
        percent = 100 * self.done / self.total if self.total else 100
        text = f"Загружено {self.done}/{self.total} ({percent:.0f}%), прошло {elapsed / 60:.1f} мин"
        if self.done and self.done < self.total:
            left = elapsed / self.done * (self.total - self.done)
            text += f", осталось ≈ {left / 60:.0f} мин"
        return text


async def _ticker(progress, log):
    while True:
        await asyncio.sleep(TICK_SECONDS)
        if progress.done:
            log(progress.line())


async def run(
    bot,
    db,
    styles,
    *,
    owner_id=DEFAULT_OWNER_ID,
    concurrency=DEFAULT_CONCURRENCY,
    dry_run=False,
    keep_old=False,
    delete_delay=DEFAULT_DELETE_DELAY,
    retry_padding=1.0,
    log=print,
):
    """Возвращает True, если все стили в порядке."""
    me = await bot.get_me()
    log(f"Паки будут принадлежать боту @{me.username}")

    plans = [make_plan(style, await db.get_clock_packs(style.id)) for style in styles]
    for plan in plans:
        mark = "✓" if plan.action == "skip" else "→"
        extra = f", паков {plan.style.pack_count}, картинок {len(plan.style.slots)}"
        log(
            f"{mark} {plan.style.id}: {plan.reason}"
            + (extra if plan.action == "build" else "")
        )

    todo = [plan for plan in plans if plan.action == "build"]
    if not todo:
        log("Всё актуально, делать нечего.")
        return True
    if dry_run:
        log("Это был план (--dry-run), ничего не изменено.")
        return True

    tg = Telegram(bot, retry_padding=retry_padding, log=log)
    progress = Progress(sum(len(plan.style.slots) for plan in todo))
    semaphore = asyncio.Semaphore(max(1, concurrency))
    failed = []

    async def one_pack(plan, index):
        async with semaphore:
            return await build_pack(
                tg, owner_id, me.username, plan.style, index, progress, log
            )

    async def one_style(plan):
        style = plan.style
        results = await asyncio.gather(
            *(one_pack(plan, i) for i in range(style.pack_count)),
            return_exceptions=True,
        )
        errors = [r for r in results if isinstance(r, BaseException)]
        if errors:
            for error in errors:
                log(f"[{style.id}] ОШИБКА: {error!r}")
            failed.append(style.id)
            return

        names = [name for name, _ in results]
        rows = emoji_rows(style, [ids for _, ids in results])
        packs = [
            (i, names[i], len(style.pack_slots(i))) for i in range(style.pack_count)
        ]
        await db.swap_clock_style(style.id, packs, rows)
        log(f"[{style.id}] переключено на новые паки ({len(rows)} минут)")

        old_names = [r["pack_name"] for r in plan.live if r["pack_name"] not in names]
        if not old_names:
            return
        if keep_old:
            log(
                f"[{style.id}] старые паки оставлены (--keep-old): {', '.join(old_names)}"
            )
            return
        log(
            f"[{style.id}] старых паков: {len(old_names)}, удалю через {delete_delay} с"
        )
        await asyncio.sleep(delete_delay)
        for name in old_names:
            try:
                await tg.delete_set(name)
                log(f"[{style.id}] удалён {name}")
            except Exception as exc:
                log(
                    f"[{style.id}] не удалось удалить {name}: {exc!r} (удалите вручную в @Stickers)"
                )

    ticker = asyncio.create_task(_ticker(progress, log))
    try:
        await asyncio.gather(*(one_style(plan) for plan in todo))
    finally:
        ticker.cancel()

    log(progress.line())
    log(f"Готово. flood-пауз: {tg.flood_waits}")
    if tg.flood_waits > 10:
        log("Много flood-пауз: попробуйте --concurrency 4")
    if failed:
        log(
            f"Не завершены стили: {', '.join(failed)} — запустите команду ещё раз, она продолжит."
        )
    return not failed
