"""Text normalization that defeats common filter-evasion tricks.

Each token is reduced to a "skeleton": lowercase ASCII letters only, with
Turkish characters folded, leetspeak decoded, look-alike Cyrillic letters
mapped to Latin, invisible characters removed and repeated letters collapsed.
"g3r!zek@lııı" and "gerizekalı" both become "gerizekali".
"""

import re
import unicodedata
from dataclasses import dataclass

_INVISIBLE = dict.fromkeys(map(ord, "​‌‍⁠﻿­"), None)
_HOMOGLYPHS = str.maketrans("аеорсухкмтві", "aeopcyxkmtbi")  # Cyrillic -> Latin
_LEET = str.maketrans("013457@$!|€", "oieastasiie")
_REPEATS = re.compile(r"(.)\1+")
_NON_LETTERS = re.compile(r"[^a-z]+")
_HAS_LETTER = re.compile(r"[^\W\d_]")
_TOKENS = re.compile(r"\S+")


@dataclass(frozen=True, slots=True)
class Token:
    start: int
    end: int
    skeleton: str


def skeleton(word: str) -> str:
    text = unicodedata.normalize("NFKC", word.translate(_INVISIBLE))
    text = text.replace("İ", "i").lower()
    text = "".join(c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c))
    text = text.translate(_HOMOGLYPHS).replace("ı", "i")
    text = text.lstrip("\"'([{<").rstrip(".,!?;:\"')]}>")  # sentence punctuation is not leetspeak
    if _HAS_LETTER.search(text):
        text = text.translate(_LEET)
    text = _NON_LETTERS.sub("", text)
    return _REPEATS.sub(r"\1", text)


def tokenize(text: str) -> list[Token]:
    return [Token(m.start(), m.end(), skeleton(m.group())) for m in _TOKENS.finditer(text)]


def normalized_text(text: str) -> str:
    """Whole-message skeleton, used as classifier input."""
    return " ".join(t.skeleton for t in tokenize(text) if t.skeleton)
