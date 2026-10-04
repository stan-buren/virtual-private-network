"""Profile-driven VPN server catalog.

The provider profile (sing-box JSON from the subscription) is the single source
of truth for which servers exist.  This module derives a CLI-friendly catalog
from its proxy outbounds, so there is no hand-maintained server registry.
"""

from __future__ import annotations

import re
from typing import Any

from vpn.core.ports import ServerInfo

PROXY_OUTBOUND_TYPES = frozenset(
    {
        "vless",
        "vmess",
        "trojan",
        "hysteria2",
        "hysteria",
        "shadowsocks",
        "shadowsocksr",
        "tuic",
        "anytls",
        "wireguard",
    }
)

_EMOJI_RE = re.compile(
    "["
    + chr(0x1F1E0) + "-" + chr(0x1F1FF)
    + chr(0x1F300) + "-" + chr(0x1F5FF)
    + chr(0x1F600) + "-" + chr(0x1F64F)
    + chr(0x1F680) + "-" + chr(0x1F6FF)
    + chr(0x1F900) + "-" + chr(0x1F9FF)
    + chr(0x2600) + "-" + chr(0x27BF)
    + chr(0x200D) + chr(0xFE0F)
    + chr(0x00A9) + chr(0x00AE)
    + chr(0x2800) + "-" + chr(0x28FF)
    + "]+"
)

_COUNTRY_BY_NAME = {
    "германия": "de",
    "нидерланды": "nl",
    "эстония": "ee",
    "финляндия": "fi",
    "сша": "us",
    "япония": "jp",
    "турция": "tr",
    "швейцария": "ch",
    "польша": "pl",
    "россия": "ru",
    "латвия": "lv",
    "казахстан": "kz",
    "литва": "lt",
    "швеция": "se",
    "норвегия": "no",
    "дания": "dk",
    "великобритания": "gb",
    "англия": "gb",
    "франция": "fr",
    "испания": "es",
    "италия": "it",
    "австрия": "at",
    "бельгия": "be",
    "чехия": "cz",
    "румыния": "ro",
    "болгария": "bg",
    "украина": "ua",
    "молдова": "md",
    "сербия": "rs",
    "венгрия": "hu",
    "канада": "ca",
    "бразилия": "br",
    "индия": "in",
    "сингапур": "sg",
    "гонконг": "hk",
    "корея": "kr",
    "австралия": "au",
    "ирландия": "ie",
    "португалия": "pt",
    "греция": "gr",
}

_TRANSLIT = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "e",
    "ж": "zh", "з": "z", "и": "i", "й": "y", "к": "k", "л": "l", "м": "m",
    "н": "n", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u",
    "ф": "f", "х": "h", "ц": "ts", "ч": "ch", "ш": "sh", "щ": "shch",
    "ъ": "", "ы": "y", "ь": "", "э": "e", "ю": "yu", "я": "ya",
}


def normalize_tag(tag: str) -> str:
    """Strip emoji, '(Без рекламы)', and collapse whitespace from a tag."""
    tag = _EMOJI_RE.sub("", tag)
    tag = tag.replace("(Без рекламы)", "")
    return " ".join(tag.split()).strip()


def _flag_country(tag: str) -> str | None:
    """Extract an ISO country code from a leading flag emoji, if present."""
    letters = [
        chr(ord(ch) - 0x1F1E6 + ord("a"))
        for ch in tag
        if 0x1F1E6 <= ord(ch) <= 0x1F1FF
    ]
    if len(letters) >= 2 and all("a" <= ch <= "z" for ch in letters[:2]):
        return letters[0] + letters[1]
    return None


def _country(tag: str) -> str:
    """Best-effort ISO country code for a provider tag (flag first, then name)."""
    flag = _flag_country(tag)
    if flag:
        return flag
    norm = normalize_tag(tag)
    if " - " in norm:
        name = norm.rsplit(" - ", 1)[-1].strip().lower()
        if name in _COUNTRY_BY_NAME:
            return _COUNTRY_BY_NAME[name]
    return ""


def _slugify(text: str) -> str:
    """Transliterate a short name to an ascii, lowercase CLI slug."""
    out: list[str] = []
    for ch in text.lower():
        if ch in _TRANSLIT:
            out.append(_TRANSLIT[ch])
        elif ch.isascii() and ch.isalnum():
            out.append(ch)
    return "".join(out)


def _base_name(tag: str) -> str:
    """Derive the base CLI slug from a provider tag (e.g. 'Хёллентэлер - ...')."""
    norm = normalize_tag(tag)
    label = norm.split(" - ", 1)[0].strip() or norm
    parts = label.split()
    first = parts[0] if parts else label
    return _slugify(first) or _slugify(norm) or "server"


def build_catalog(profile: dict[str, Any]) -> list[ServerInfo]:
    """Build the server catalog from a provider profile's proxy outbounds.

    Names are derived from the outbound tag (transliterated).  When two servers
    share a base name, the ISO country code is appended (e.g. yauk_de).
    """
    records: list[tuple[str, str, str, str, int]] = []
    for outbound in profile.get("outbounds", []):
        if outbound.get("type") not in PROXY_OUTBOUND_TYPES:
            continue
        tag = outbound.get("tag")
        if not tag:
            continue
        records.append(
            (
                _base_name(tag),
                tag,
                _country(tag),
                outbound.get("server", "unknown"),
                outbound.get("server_port", 443),
            )
        )

    bases = [r[0] for r in records]
    duplicated = {base for base in bases if bases.count(base) > 1}

    servers: list[ServerInfo] = []
    for base, tag, country, host, port in records:
        name = base + "_" + country if base in duplicated and country else base
        servers.append(
            ServerInfo(name=name, tag=tag, country=country, host=host, port=port)
        )
    return sorted(servers, key=lambda s: s.name)
