"""Personal-information detection (Roblox-style: children must not share contact details)."""

import re
from dataclasses import dataclass

_PATTERNS = {
    "email": re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+"),
    "phone": re.compile(r"(?<!\d)(?:\+?\d[\s.-]?){10,13}(?!\d)"),
    "url": re.compile(
        r"(?:https?://|www\.)\S+|\b[\w-]+\.(?:com|net|org|gg|io|me|tr|xyz|ly)(?:/\S*)?\b",
        re.IGNORECASE,
    ),
    "social_handle": re.compile(
        r"\b(?:discord|dc|insta(?:gram)?|ig|snap(?:chat)?|tiktok|telegram|whatsapp|wp)\b"
        r"\s*[:=\-]?\s*@?[\w.#]{3,}",
        re.IGNORECASE,
    ),
}


@dataclass(frozen=True, slots=True)
class PiiHit:
    start: int
    end: int
    kind: str


def find_pii(text: str) -> list[PiiHit]:
    return [
        PiiHit(m.start(), m.end(), kind)
        for kind, pattern in _PATTERNS.items()
        for m in pattern.finditer(text)
    ]
