"""Listed profanity in the ORIGINAL text, with character offsets, so it can be starred in place.

The word list and the decoding of disguises (f*ck, sh1t, а$$ with Cyrillic letters, fck) are the team's
temizlik.py; this module only maps them back onto the text as the platform sent it. temizlik.temizle()
rewrites the whole text for the models, which loses the offsets.
"""
import re
import unicodedata
from dataclasses import dataclass

import temizlik

LETTER = r"[^\W\d_]"
# f u c k, s.h.i.t, f-u-c-k: three or more single letters with one or two separators between them
SPACED = re.compile(rf"(?<!\w)(?:{LETTER}[ .\-_*]{{1,2}}){{2,}}{LETTER}(?!\w)")
TOKEN = re.compile(r"\S+")
# Listed phrases written out ("kys" -> "kill yourself"): the list's keys are single words, so "kill yourself"
# itself is only found here. Phrases with a listed word of their own ("what the fuck") are left to that word.
PHRASES = sorted({a for a in temizlik.ASIL.values()
                  if " " in a and not any(w in temizlik.ASIL for w in a.split())}, key=len, reverse=True)
PHRASE = re.compile(r"(?<!\w)(?:" + "|".join(r"\s+".join(map(re.escape, p.split())) for p in PHRASES) + r")(?!\w)",
                    re.I) if PHRASES else None


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

    for m in PHRASE.finditer(text) if PHRASE else ():
        word = " ".join(m.group(0).lower().split())
        hits.append(Hit(m.start(), m.end(), m.group(0), word, temizlik.SEVIYE.get(word, 5), False))
        taken.append((m.start(), m.end()))

    for m in SPACED.finditer(text):
        if any(s < m.end() and m.start() < e for s, e in taken):
            continue
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
