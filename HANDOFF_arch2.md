# HANDOFF_arch2 — задача 4 «Арх.2» — выполнена

Тесты: 388 passed на SQLite и на Postgres 16 (376 прежних + 12 новых в `tests/test_features_layout.py`).
Миграции 1–17 на чистом Postgres: `aerich upgrade` проходит, `aerich migrate` после — «No changes detected»
(схема не менялась, новой миграции нет; следующая — 18).

## Что сделано
| Что | Решение |
|---|---|
| `modules/` → `commands/` | Только простые команды без состояния (dice, flip, calc, qr, wanted, archive-команды…). Тексты — `commands/locales/`. Имена «модулей» в настройках пользователя (`DisabledModule`) НЕ менялись. |
| Фичи | `app/features/{mute,profile,reminders,templates}/`: `models.py` (только модель), `service.py` (запросы и логика без aiogram), `bot.py` (команды/транспорт), `api.py` (где было), `locales/`. |
| Игры | Код игр (`ttt, checkers, minesweeper, g2048, quiz, rps, hangman, wordle, city, guess_number`) переехал в `app/features/games/bot/`, тексты — `games/locales/`. `handlers/games.py` удалён, общий router — `games/bot/__init__.py`. Это не было в списке задачи, но иначе в `commands/` остались бы ~1500 строк состоятельных игр. |
| Реестр фич | `app/features/__init__.py: FEATURES` — явный список. `core/loader.load_commands()` (бывший `load_modules`) импортирует `commands.*` и `app.features.<f>.bot`; `i18n` собирает `locales` каждой фичи. |
| Напоминания | `core/reminders.py` удалён: чистая логика и запросы → `service.py`; отправка (`render_list`, `process_owner`, `run_reminders_loop`) и `.waiting` → `bot.py`. |
| Модели | В `config.TORTOISE_ORM` новые пути моделей; из `db/models/__init__.py` убраны `Mute`, `ProfileBackup`. Запросы к этим таблицам импортируются из `service.py` фич. |
| Находка | Тест раскладки поймал, что после переноса не регистрировались `.hangman/.city/.guess` (loader импортирует пакет, а не файлы) — исправлено явным импортом в `games/bot/__init__.py`, тест закреплён. |

## Решения
- `mute`: `handle_incoming` (хук pipeline) остался в `bot.py` — он принимает `bot`/`message`.
- Запросы мутов/шаблонов/профиля пока возвращают dict (как раньше); переход на модели — позже.
- Остались в `core/`/`modules`-стиле и переезжают дальше: `archive*` (Арх.3), middleware и `handlers/business_messages.py` (Арх.4), `autoresponder, ai, scheduler, stt, story…`.
- Ruff: новые файлы `app/features` отформатированы и без F-замечаний; старые замечания в других файлах не трогал.

## Заливка
```bash
git checkout -b arch2
# в папке проекта удалить всё, КРОМЕ папки .git и файла .env
# распаковать arch2_backend.zip в эту папку
git add -A
git commit -m "Arch 2: modules -> commands, features mute/profile/reminders/templates/games"
uv sync --frozen && uv run pytest        # красные — НЕ сливать
git push -u origin arch2                 # PR → Merge
```
Миграций нет, фронтенд не менялся, env не менялись.

## Проверить после деплоя
- В мини-приложении «Команды» и «Настройки → модули» те же списки; отключённые модули остались отключёнными.
- `.mute`, `.wmute`, `.t`, `.profile`/`.restore`, `.waiting`; напоминания приходят (лог без «Сбой цикла напоминаний»).
- Игры: `.ttt`, `.chk`, `.ms`, `.2048`, `.quiz`, `.rps`, а главное `.hangman`, `.word`, `.city`, `.guess`.
- Обновить `HANDOFF_audit.md`: строка 4 (Арх.2) → «выполнено (`HANDOFF_arch2.md`)»; в `PROJECT_CONTEXT.md` раздел 3 (`modules/` → `commands/` и `app/features/`).
