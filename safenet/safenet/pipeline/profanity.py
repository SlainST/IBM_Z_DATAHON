"""Listed profanity in the ORIGINAL text, with character offsets, so it can be starred in place.

The word list and the decoding of disguises (f*ck, sh1t, а$$ with Cyrillic letters, fck) are the team's
temizlik.py; this module only maps them back onto the text as the platform sent it. temizlik.temizle()
rewrites the whole text for the models, which loses the offsets.
"""
import re
import unicodedata
from dataclasses import dataclass
from functools import lru_cache

import temizlik

LETTER = r"[^\W\d_]"
# f u c k, s.h.i.t, f-u-c-k: three or more single letters with one or two separators between them
SPACED = re.compile(rf"(?<!\w)(?:{LETTER}[ .\-_*]{{1,2}}){{2,}}{LETTER}(?!\w)")
TOKEN = re.compile(r"\S+")


@lru_cache(maxsize=1)
def phrases() -> list[tuple[re.Pattern, str]]:
    """Listed phrases written out in full. "kys" is listed as "kill yourself" and neither "kill" nor "yourself" is
    a listed word, so the phrase itself is looked for: "kill yourself", "kill urself", "kill your self".
    A phrase with a listed word in it ("what the fuck") is already found through that word."""
    out = []
    for phrase in sorted(set(temizlik.ASIL.values())):
        parts = phrase.split()
        if len(parts) < 2 or any(p in temizlik.ASIL for p in parts):
            continue
        body = r"\s+".join(r"(?:your|ur)\s*self" if p == "yourself" else re.escape(p) for p in parts)
        out.append((re.compile(rf"(?<!\w){body}(?!\w)", re.I), phrase))
    return out


@dataclass(frozen=True, slots=True)
class Hit:
    start: int
    end: int
    written: str      # as in the text: "f*cking"
    word: str         # the listed word: "fucking"
    severity: int     # 1-10 from kufur_listesi.csv
    hidden: bool      # disguised: adds hiding points


def _plain(core: str) -> str:
    t = unicodedata.normalize("NFKC", core).lower()
    return temizlik._aksansiz(temizlik.GORUNMEZ.sub("", t).translate(temizlik.BENZER_HARFLER))


def _lookup(core: str) -> tuple[str, bool] | None:
    lowered = unicodedata.normalize("NFKC", core).lower()
    plain = _plain(core)
    letters_changed = plain != lowered
    if plain in temizlik.ASIL:
        word = temizlik.ASIL[plain]
        return word, letters_changed or word != plain
    found = temizlik._kelime_coz(plain)
    if found:
        return found[0], found[1] or letters_changed
    return None


def find(text: str) -> list[Hit]:
    hits: list[Hit] = []
    taken: list[tuple[int, int]] = []

    for m in SPACED.finditer(text):
        positions = [m.start() + i for i, c in enumerate(m.group(0)) if c.isalpha()]
        letters = "".join(text[p].lower() for p in positions)
        done = False
        for size in range(len(letters), 2, -1):
            for first in range(len(letters) - size + 1):
                word = temizlik.ASIL.get(letters[first:first + size])
                if word:
                    s, e = positions[first], positions[first + size - 1] + 1
                    hits.append(Hit(s, e, text[s:e], word, temizlik.SEVIYE.get(word, 5), True))
                    taken.append((s, e))
                    done = True
                    break
            if done:
                break

    for pattern, phrase in phrases():
        for m in pattern.finditer(text):
            if any(s < m.end() and m.start() < e for s, e in taken):
                continue
            hits.append(Hit(m.start(), m.end(), m.group(0), phrase, temizlik.SEVIYE.get(phrase, 5), False))
            taken.append((m.start(), m.end()))

    for m in TOKEN.finditer(text):
        if any(s < m.end() and m.start() < e for s, e in taken):
            continue
        before, core, _ = temizlik.KENAR.fullmatch(m.group(0)).groups()
        if not core or len(core) > 40:
            continue
        found = _lookup(core)
        if found:
            s = m.start() + len(before)
            word, hidden = found
            hits.append(Hit(s, s + len(core), core, word, temizlik.SEVIYE.get(word, 5), hidden))
    return sorted(hits, key=lambda h: h.start)


def star(text: str, hits) -> str:
    """Keeps the first letter of each listed word and stars the rest: fuck -> f***, f u c k -> f * * *."""
    chars = list(text)
    for h in hits:
        first = True
        for i in range(h.start, h.end):
            if chars[i].isspace():
                continue
            if first and chars[i].isalnum():
                first = False
                continue
            first = False
            chars[i] = "*"
    return "".join(chars)


def word_count(text: str, hits) -> int:
    """Words in the message, counting a spaced-out word (f u c k) once."""
    n = sum(1 for t in TOKEN.findall(text) if re.search(r"\w", t))
    for h in hits:
        n -= max(0, len(TOKEN.findall(h.written)) - 1)
    return max(n, 1)
