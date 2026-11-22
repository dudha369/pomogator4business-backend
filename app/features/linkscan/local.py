"""Локальные проверки ссылок и файлов: без сети и без aiogram.

Ссылки достаются из сущностей сообщения (`url` и `text_link`). Главный признак
подмены — отображаемый текст выглядит как один адрес, а ведёт ссылка на другой."""

import ipaddress
import re
import unicodedata
from dataclasses import dataclass
from urllib.parse import urlsplit

from app.features.linkscan.verdict import NOTE, SUSPICIOUS, Verdict

MAX_URL_LEN = 2048

SHORTENERS = frozenset(
    [
        "bit.ly",
        "t.co",
        "tinyurl.com",
        "goo.gl",
        "is.gd",
        "cutt.ly",
        "ow.ly",
        "rebrand.ly",
        "t.ly",
        "tiny.cc",
        "shorturl.at",
        "clck.ru",
        "vk.cc",
        "rb.gy",
        "buff.ly",
        "s.id",
        "v.gd",
        "lnkd.in",
        "qr.ae",
        "u.to",
    ]
)
# зоны, которыми непропорционально часто пользуются для фишинга; сами по себе — только заметка
RISKY_TLDS = frozenset(
    [
        "zip",
        "mov",
        "top",
        "xyz",
        "click",
        "icu",
        "cfd",
        "sbs",
        "tk",
        "ml",
        "ga",
        "cf",
        "gq",
        "work",
        "rest",
        "country",
        "kim",
        "loan",
        "bid",
    ]
)
# исполняемые и скриптовые: опасны сами по себе (их же маскируют двойным расширением)
EXECUTABLE_EXTENSIONS = frozenset(
    [
        "apk",
        "exe",
        "msi",
        "scr",
        "bat",
        "cmd",
        "com",
        "js",
        "jse",
        "vbs",
        "vbe",
        "wsf",
        "ps1",
        "jar",
        "lnk",
        "iso",
        "img",
        "dll",
        "hta",
        "reg",
        "docm",
        "xlsm",
        "pptm",
    ]
)
# контейнеры и документы с историей эксплойтов (pdf, офис, архивы, html): для них стоит
# второе мнение (VirusTotal), а картинки, музыка и видео — нет
RISKY_EXTENSIONS = EXECUTABLE_EXTENSIONS | frozenset(
    [
        "zip",
        "rar",
        "7z",
        "ace",
        "tar",
        "gz",
        "cab",
        "pdf",
        "doc",
        "docx",
        "xls",
        "xlsx",
        "ppt",
        "pptx",
        "rtf",
        "odt",
        "ods",
        "odp",
        "chm",
        "html",
        "htm",
        "svg",
        "eml",
    ]
)
DOCUMENT_EXTENSIONS = frozenset(
    ["pdf", "doc", "docx", "xls", "xlsx", "txt", "jpg", "jpeg", "png", "mp4", "mp3"]
)
# в Telegram и так знают свои адреса; запросы к сторонним сервисам про них — лишняя трата лимита
TRUSTED_HOSTS = frozenset({"t.me", "telegram.me", "telegram.org", "telegra.ph"})

_LOOKS_LIKE_URL = re.compile(
    r"^(?:https?://)?(?:[^\s/@:?#]+@)?([^\s/@:?#]+\.[^\W\d_]{2,})(?::\d+)?(?:[/?#]\S*)?$",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class Link:
    display: str  # что видит читатель
    url: str  # куда ведёт на самом деле (нормализованный http(s)-адрес)
    host: str  # ASCII-вид хоста (punycode)


def entity_text(text: str, offset: int, length: int) -> str:
    """Срез по смещениям Telegram: они считаются в единицах UTF-16, а не символах Python."""
    raw = text.encode("utf-16-le")[offset * 2 : (offset + length) * 2]
    return raw.decode("utf-16-le", errors="ignore")


_OTHER_SCHEME = re.compile(r"^[a-z][a-z0-9+.\-]*:(?!\d+(?:/|$))", re.IGNORECASE)


def _with_scheme(raw: str) -> str:
    """Адрес без схемы считаем http. `javascript:...` — это чужая схема, а `host:8080` — порт."""
    if "://" in raw or _OTHER_SCHEME.match(raw):
        return raw
    return f"http://{raw}"


def _host_of(raw: str) -> tuple[str, str] | None:
    """(unicode-хост, ASCII-хост) или None, если это не http(s)-адрес."""
    try:
        parts = urlsplit(_with_scheme(raw))
        host = parts.hostname
    except ValueError:
        return None
    if parts.scheme not in ("http", "https") or not host:
        return None
    try:
        return host, host.encode("idna").decode("ascii")
    except UnicodeError:
        return None


def make_link(display: str, raw_url: str) -> Link | None:
    raw_url = raw_url.strip()
    if not raw_url or len(raw_url) > MAX_URL_LEN:
        return None
    hosts = _host_of(raw_url)
    if hosts is None:
        return None
    return Link(
        display=display, url=_with_scheme(raw_url).split("#", 1)[0], host=hosts[1]
    )


def extract_links(text: str | None, entities, limit: int) -> list[Link]:
    """Уникальные ссылки сообщения (не больше `limit`: спам-сообщение не должно
    превращаться в десятки запросов)."""
    links: dict[tuple[str, str], Link] = {}
    for entity in entities or ():
        if not text or entity.type not in ("url", "text_link"):
            continue
        shown = entity_text(text, entity.offset, entity.length)
        raw = shown if entity.type == "url" else getattr(entity, "url", None)
        link = make_link(shown, raw) if raw else None
        if link and (link.display, link.url) not in links:
            links[(link.display, link.url)] = link
        if len(links) >= limit:
            break
    return list(links.values())


def _in_domains(host: str, domains: frozenset[str]) -> bool:
    return any(host == d or host.endswith(f".{d}") for d in domains)


def _same_site(a: str, b: str) -> bool:
    a, b = a.removeprefix("www."), b.removeprefix("www.")
    return a == b or a.endswith(f".{b}") or b.endswith(f".{a}")


def _mixed_scripts(host: str) -> bool:
    """В одной части домена буквы разных алфавитов (латинская «a» и кириллическая «а»)."""
    for label in host.split("."):
        scripts = {unicodedata.name(ch, "?").split()[0] for ch in label if ch.isalpha()}
        if len(scripts - {"?"}) > 1:
            return True
    return False


def _is_ip(host: str) -> bool:
    try:
        ipaddress.ip_address(host)
    except ValueError:
        return False
    return True


def assess_link(link: Link) -> Verdict:
    reasons: list[tuple[str, int]] = []
    parts = urlsplit(link.url)
    unicode_host = (parts.hostname or "").lower()

    shown = _LOOKS_LIKE_URL.match(link.display.strip())
    shown_host = _host_of(shown.group(1)) if shown else None
    if shown_host and not _same_site(shown_host[1], link.host):
        reasons.append(("mismatch", SUSPICIOUS))
    if parts.username is not None:
        reasons.append(("userinfo", SUSPICIOUS))
    if _mixed_scripts(unicode_host):
        reasons.append(("lookalike", SUSPICIOUS))
    elif any(label.startswith("xn--") for label in link.host.split(".")) or not (
        unicode_host.isascii()
    ):
        reasons.append(("punycode", NOTE))
    if _in_domains(link.host, SHORTENERS):
        reasons.append(("shortener", NOTE))
    if link.host.rsplit(".", 1)[-1] in RISKY_TLDS:
        reasons.append(("bad_tld", NOTE))
    if _is_ip(link.host):
        reasons.append(("ip_host", NOTE))

    return Verdict(
        level=max((level for _, level in reasons), default=0),
        reasons=tuple(code for code, _ in reasons),
        sources=("local",) if reasons else (),
    )


def assess_file(name: str | None) -> Verdict:
    """Файл без сети: тип из группы риска и «двойное» расширение (`счёт.pdf.exe`)."""
    parts = (name or "").lower().rsplit(".", 2)
    last = parts[-1] if len(parts) > 1 else ""
    if last not in RISKY_EXTENSIONS:
        return Verdict()
    if (
        last in EXECUTABLE_EXTENSIONS
        and len(parts) == 3
        and parts[1] in DOCUMENT_EXTENSIONS
    ):
        return Verdict(SUSPICIOUS, ("double_extension",), ("local",))
    return Verdict(NOTE, ("risky_file",), ("local",))
