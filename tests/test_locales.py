"""Словари переводов: одинаковые ключи, строковые значения и одинаковые
плейсхолдеры во всех языках. Именно такие расхождения (кортеж вместо строки,
{mention} в одном языке и {name} в другом) ломали игры, а t() молча возвращает
сырой шаблон, поэтому в рантайме это не видно."""

import re
import string

from core.i18n import LOCALES

_formatter = string.Formatter()


def placeholders(template):
    return {name for _, name, _, _ in _formatter.parse(template) if name}


def test_all_values_are_strings():
    bad = [
        (lang, key)
        for lang, table in LOCALES.items()
        for key, value in table.items()
        if not isinstance(value, str)
    ]
    assert bad == []


def test_languages_have_the_same_keys():
    ru = set(LOCALES["ru"])
    for lang in ("en", "uk"):
        assert ru - set(LOCALES[lang]) == set(), f"в {lang} нет ключей из ru"
        assert set(LOCALES[lang]) - ru == set(), f"в {lang} лишние ключи"


def test_placeholders_match_across_languages():
    mismatches = []
    for key, template in LOCALES["ru"].items():
        for lang in ("en", "uk"):
            other = LOCALES[lang].get(key)
            if isinstance(template, str) and isinstance(other, str):
                if placeholders(template) != placeholders(other):
                    mismatches.append(
                        (key, lang, placeholders(template), placeholders(other))
                    )
    assert mismatches == []


def test_html_game_texts_have_no_stray_angle_brackets():
    """Игры шлют текст с parse_mode=html: «<» вне тегов ломает сообщение."""
    stray = []
    for key, template in LOCALES["ru"].items():
        if key.startswith(("ttt.", "chk.")):
            without_tags = re.sub(r"</?[a-zA-Z-]+(\s[^>]*)?>", "", template)
            if "<" in without_tags or "&" in re.sub(
                r"&(amp|lt|gt|quot);", "", without_tags
            ):
                stray.append(key)
    assert stray == []
