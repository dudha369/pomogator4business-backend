"""parse_mode у исходящих текстов: общие проверки для всего проекта.

1. Модульные тесты guard'а (`tests/html_guard.py`).
2. Динамика: любой тест с фикстурой `bot` падает, если бот отправил HTML без
   parse_mode (или с parse_mode=html, но с неэкранированным `<`/`&`).
3. Статика: AST-сканер всех вызовов отправки в коде — не покрытые тестами пути тоже
   ловятся. Текст считается HTML, если в нём (или в переводе по ключу `t("…")`, или
   в переменной, собранной из такого) есть наши теги или вызов HTML-сборщика."""

import ast
from pathlib import Path

import pytest

from app.platform.i18n import LOCALES
from tests.html_guard import _TAG, problems

ROOT = Path(__file__).resolve().parent.parent
SCAN_DIRS = ("app", "commands", "core", "handlers", "api", "mirror")

# --- 1. guard ---------------------------------------------------------------


def test_guard_flags_html_without_parse_mode():
    assert problems("send_message", {"text": "<b>x</b>"})
    assert problems("send_photo", {"caption": '<tg-emoji emoji-id="1">📦</tg-emoji>'})
    assert problems("send_message", {"text": "a &lt; b"})


def test_guard_accepts_correct_calls():
    assert not problems("send_message", {"text": "<b>x</b>", "parse_mode": "html"})
    assert not problems("send_message", {"text": "a < b & c"})  # обычный текст
    assert not problems("send_message", {"text": "<b>x</b>", "entities": [object()]})
    assert not problems("send_message", {"text": "5 &lt; 6", "parse_mode": "html"})


def test_guard_flags_unescaped_text_in_html_mode():
    assert problems("send_message", {"text": "a < b", "parse_mode": "html"})
    assert problems("send_message", {"text": "Tom & Jerry", "parse_mode": "html"})
    assert problems("edit_message_text", {"text": "<script>", "parse_mode": "html"})


# --- 2. динамика: уведомления архива с «опасным» текстом ---------------------


@pytest.mark.asyncio
async def test_archive_notices_escape_user_text(bot, connection):
    from app.features.archive.render.classic import (
        before_after as _before_after,
        highlight_changes,
    )
    from app.features.archive.render.classic import build_notice

    evil = "<b>1</b> & <tg-emoji emoji-id='1'>x</tg-emoji> </blockquote>"
    snap = {"kind": "text", "text": evil, "forward": {"name": "<i>X</i> & Y"}}
    for limit in (4096, 40):
        notice = build_notice("ru", "<b>m</b>", snap, limit=limit)
        assert not problems("send_message", {"text": notice, "parse_mode": "html"})
    # «Было/Стало» тоже экранируют текст целиком
    text = await _before_after("ru", evil, evil + "<")
    assert not problems("send_message", {"text": text, "parse_mode": "html"})
    assert "<b>1</b>" not in highlight_changes("", evil)


# --- 3. статика --------------------------------------------------------------

# метод -> (позиционный индекс текста или None; текст всегда передаётся и по ключу)
_TEXT_ARG = {
    "send_message": None,
    "edit_message_text": None,
    "edit_message_caption": None,
    "send_photo": None,
    "send_video": None,
    "send_animation": None,
    "send_audio": None,
    "send_voice": None,
    "send_document": None,
    "edit_text": 0,
    "edit_caption": 0,
    "answer": 0,  # message.answer(text); call.answer() — тост, см. _TOAST
    "reply": 0,  # ctx.reply
    "present": 0,
    "usage_error": 0,
    "edit_command_message": 0,
}
_TOAST = {"call", "callback", "query", "cq"}
_HTML_BUILDERS = {
    "build_notice",
    "render_text",
    "format_mention",
    "format_forward",
    "highlight_changes",
    "highlight_changes_async",
    "kind_detail",
    "_before_after",
    "before_after",
    "mention",
}


def _locale_has_html(key: str) -> bool:
    return any(_TAG.search(strings.get(key, "")) for strings in LOCALES.values())


class _Scanner(ast.NodeVisitor):
    def __init__(self, path):
        self.path = path
        self.found = []
        self._assigned = [{}]  # стек: имя -> выражения, присвоенные в функции

    def visit_FunctionDef(self, node):
        scope = {}
        for sub in ast.walk(node):
            if isinstance(sub, ast.Assign):
                for target in sub.targets:
                    if isinstance(target, ast.Name):
                        scope.setdefault(target.id, []).append(sub.value)
            elif isinstance(sub, ast.AugAssign) and isinstance(sub.target, ast.Name):
                scope.setdefault(sub.target.id, []).append(sub.value)
        self._assigned.append(scope)
        self.generic_visit(node)
        self._assigned.pop()

    visit_AsyncFunctionDef = visit_FunctionDef

    def _html_like(self, expr, seen=()):
        for node in ast.walk(expr):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                if _TAG.search(node.value):
                    return True
            elif isinstance(node, ast.Call):
                fn = node.func
                name = fn.id if isinstance(fn, ast.Name) else getattr(fn, "attr", "")
                if name in _HTML_BUILDERS:
                    return True
                if name == "t" and node.args:
                    key = node.args[0]
                    if isinstance(key, ast.Constant) and _locale_has_html(key.value):
                        return True
            elif isinstance(node, ast.Name) and node.id not in seen:
                for value in self._assigned[-1].get(node.id, []):
                    if self._html_like(value, seen + (node.id,)):
                        return True
        return False

    def visit_Call(self, node):
        self.generic_visit(node)
        fn = node.func
        if not isinstance(fn, ast.Attribute) or fn.attr not in _TEXT_ARG:
            return
        if fn.attr == "answer" and isinstance(fn.value, ast.Name):
            if fn.value.id in _TOAST:
                return
        kwargs = {k.arg for k in node.keywords}
        if None in kwargs or {"parse_mode", "entities", "caption_entities"} & kwargs:
            return  # parse_mode задан явно (в т.ч. None) либо **kwargs
        exprs = [k.value for k in node.keywords if k.arg in ("text", "caption")]
        index = _TEXT_ARG[fn.attr]
        if index is not None and len(node.args) > index:
            exprs.append(node.args[index])
        if any(self._html_like(e) for e in exprs):
            self.found.append(f"{self.path.relative_to(ROOT)}:{node.lineno} .{fn.attr}")


def _scan_all():
    found = []
    for folder in SCAN_DIRS:
        for path in sorted((ROOT / folder).rglob("*.py")):
            scanner = _Scanner(path)
            scanner.visit(ast.parse(path.read_text(encoding="utf-8")))
            found += scanner.found
    return found


def test_no_html_text_is_sent_without_parse_mode():
    """Если упало: добавьте parse_mode="html" (или parse_mode=None для обычного текста)."""
    assert not _scan_all()


def test_scanner_catches_known_bad_pattern(tmp_path, monkeypatch):
    src = 'async def f(bot):\n    await bot.send_message(chat_id=1, text="<b>x</b>")\n'
    path = ROOT / "app" / "_tmp_scan_probe.py"
    path.write_text(src, encoding="utf-8")
    try:
        scanner = _Scanner(path)
        scanner.visit(ast.parse(src))
    finally:
        path.unlink()
    assert scanner.found
