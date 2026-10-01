import os

from core.locales.en import EN
from core.locales.ru import RU
from core.locales.uk import UK

OUTPUT_THEMES_DIR = "core/locales/themes"
OUTPUT_MODULES_DIR = "modules/locales"

LANGS = {"RU": RU, "EN": EN, "UK": UK}

KEY_RENAMES = {
    "words.usage": "split.usage",
    "cmddesc.words": "cmddesc.split",
}

THEME_PREFIXES = {
    "common": "common",
    "start": "start",
    "connection": "connection",
    "settings": "settings",
    "language": "language",
    "mirror": "mirror",
    "emoji_status": "emoji_status",
}

MODULE_PREFIXES = {
    "bomb": "bomb",
    "check": "check",
    "dem": "dem",
    "echo": "echo",
    "fake": "fake",
    "mute": "mute",
    "wmute": "mute",
    "pet": "pet",
    "profile": "profile",
    "quote": "quote",
    "story": "story",
    "text": "text_",
    "timer": "timer",
    "tr": "tr",
    "typing": "typing_",
    "wanted": "wanted",
    "split": "split",
    "ascii": "ascii_",
    "panic": "panic",
    "archive": "archive",
    "scam": "scam",
    "voice": "voice_effects",
    "stt": "stt",
    "ttt": "ttt",
    "wordle": "wordle",
    "chk": "checkers",
    "ms": "minesweeper",
    "rps": "rps",
    "guess": "guess_number",
    "roast": "roast_compliment",
    "compliment": "roast_compliment",
    "eightball": "eightball",
    "calc": "calc",
    "qr": "qr",
    "poll": "poll",
    "hangman": "hangman",
    "quiz": "quiz",
    "city": "city",
    "g2048": "g2048",
    "spam": "spam",
    "sw": "sw",
}

CMDDESC_TARGETS = {
    "2048": "g2048",
    "8ball": "eightball",
    "ascii": "ascii_",
    "bball": "dice",
    "bomb": "bomb",
    "bowl": "dice",
    "calc": "calc",
    "check": "check",
    "chk": "checkers",
    "city": "city",
    "compliment": "roast_compliment",
    "dart": "dice",
    "dem": "dem",
    "dice": "dice",
    "echo": "echo",
    "fake": "fake",
    "flip": "flip",
    "football": "dice",
    "guess": "guess_number",
    "haha": "haha",
    "hangman": "hangman",
    "joke": "joke",
    "ms": "minesweeper",
    "mute": "mute",
    "panic": "panic",
    "pet": "pet",
    "plove": "plove",
    "poll": "poll",
    "profile": "profile",
    "qr": "qr",
    "quiz": "quiz",
    "quote": "quote",
    "restore": "profile",
    "roast": "roast_compliment",
    "rps": "rps",
    "slot": "dice",
    "story": "story",
    "spam": "spam",
    "storyautopost": "story",
    "stt": "stt",
    "sw": "sw",
    "text": "text_",
    "timer": "timer",
    "tr": "tr",
    "ttt": "ttt",
    "type": "type_",
    "typing": "typing_",
    "voice": "voice_effects",
    "wanted": "wanted",
    "wmute": "mute",
    "word": "wordle",
    "words": "split",
    "split": "split",
}


def _target_for(key: str) -> tuple[str, str]:
    if key.startswith("cmddesc."):
        command_name = key.split(".", 1)[1]
        target = CMDDESC_TARGETS.get(command_name)
        if target is None:
            raise ValueError(f"Нет цели для {key!r} — допиши в CMDDESC_TARGETS")
        return "module", target

    prefix = key.split(".", 1)[0]
    if prefix in THEME_PREFIXES:
        return "theme", THEME_PREFIXES[prefix]
    if prefix in MODULE_PREFIXES:
        return "module", MODULE_PREFIXES[prefix]
    raise ValueError(f"Нет цели для {key!r} — допиши в THEME_PREFIXES/MODULE_PREFIXES")


def _bucket_all():
    buckets = {}
    for lang_name, lang_dict in LANGS.items():
        for raw_key, value in lang_dict.items():
            key = KEY_RENAMES.get(raw_key, raw_key)
            bucket, target = _target_for(key)
            slot = buckets.setdefault((bucket, target), {"RU": {}, "EN": {}, "UK": {}})
            slot[lang_name][key] = value
    return buckets


def _write_file(path, dicts):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    lines = ['"""Автоматически сгенерировано scripts/split_locales.py."""\n']
    for lang_name in ("RU", "EN", "UK"):
        values = dicts[lang_name]
        if not values:
            continue
        lines.append(f"{lang_name} = {{")
        for key, value in values.items():
            lines.append(f"    {key!r}: {value!r},")
        lines.append("}")
        lines.append("")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def main():
    buckets = _bucket_all()

    for (bucket, target), dicts in buckets.items():
        directory = OUTPUT_THEMES_DIR if bucket == "theme" else OUTPUT_MODULES_DIR
        path = os.path.join(directory, f"{target}.py")
        _write_file(path, dicts)
        print(f"{bucket}:{target} -> {path}")

    for directory in (OUTPUT_THEMES_DIR, OUTPUT_MODULES_DIR):
        init_path = os.path.join(directory, "__init__.py")
        if not os.path.exists(init_path):
            open(init_path, "w").close()

    print("Готово. Проверь diff, удали core/locales/ru.py, en.py, uk.py.")


if __name__ == "__main__":
    main()
