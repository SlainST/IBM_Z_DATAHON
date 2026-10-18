"""Sentences, possible typos, game words, quotes and spam: the small text rules around the models."""
import bisect
import csv
import re
from collections import Counter
from dataclasses import dataclass
from functools import lru_cache

from ..config import ROOT

CLUE_DISTANCE = 6   # a context clue counts within this many words of the listed word

# A sentence ends at . ! ? followed by whitespace, or at a line break. "f.u.c.k" stays one word.
_BOUNDARY = re.compile(r"(?<=[.!?])\s+|\n+")
_WORD = re.compile(r"[^\W_]+(?:'[^\W_]+)?")
_CLUE_TOKEN = re.compile(r"[^\W_]+(?:'[^\W_]+)?|[\U0001F300-\U0001FAFF☀-➿]")   # words and emoji: 😂 is a clue


@dataclass(frozen=True, slots=True)
class Span:
    start: int
    end: int


def sentences(text: str) -> list[Span]:
    spans, start = [], 0
    for m in _BOUNDARY.finditer(text):
        spans.append(Span(start, m.start()))
        start = m.end()
    spans.append(Span(start, len(text)))
    out = []
    for s in spans:
        chunk = text[s.start:s.end]
        if chunk.strip():
            lead = len(chunk) - len(chunk.lstrip())
            out.append(Span(s.start + lead, s.start + len(chunk.rstrip())))
    return out or [Span(0, len(text))]


@lru_cache(maxsize=1)
def confusables() -> list[dict]:
    path = ROOT / "karistirilabilir_kelimeler.csv"
    if not path.exists():
        path = ROOT / "data" / "karistirilabilir_kelimeler.csv"
    with open(path, encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    for r in rows:
        r["clues"] = {c.strip().lower() for c in r.get("baglam_ipuclari", "").split("|") if c.strip()}
    return rows


def possible_typo(sentence: str, offset: int, hit, min_clues: int) -> dict | None:
    """'I fed the fuck at the lake': a listed word next to clues of an innocent word one key away."""
    candidates = [r for r in confusables() if r["karistirilan"] == hit.word and r["clues"]]
    if not candidates:
        return None
    words = [(m.start() + offset, m.group(0).lower()) for m in _WORD.finditer(sentence)]
    at = next((i for i, (pos, _) in enumerate(words) if pos >= hit.start), None)
    if at is None:
        return None
    near = {w for _, w in words[max(0, at - CLUE_DISTANCE):at + CLUE_DISTANCE + 1]}
    for r in candidates:
        if len(near & r["clues"]) >= min_clues:
            return {"word": hit.word, "suggestion": r["kelime"]}
    return None


@lru_cache(maxsize=1)
def _game_words() -> tuple[re.Pattern, dict[str, set]]:
    clues: dict[str, set] = {}
    for r in confusables():
        if r["kategori"] == "oyun_dili":
            clues.setdefault(r["kelime"].lower(), set()).update(r["clues"])
    words = sorted(clues, key=len, reverse=True)
    return re.compile(r"\b(" + "|".join(map(re.escape, words)) + r")(?:s|d|ed|ing|er|ers)?\b", re.I), clues


def game_words(text: str, min_clues: int, keep=()) -> list[Span]:
    """oyun_dili_serbest: the game words ('kill', 'die', 'destroy'...) used in game context, which are taken out
    before the models score the sentence. In context means at least min_clues of the word's clues
    (karistirilabilir_kelimeler.csv) within CLUE_DISTANCE words, anywhere in the message: "gg, I will kill you
    next round". A word inside a listed phrase (keep: "kill yourself") is never a game word."""
    pattern, clues = _game_words()
    tokens = [(m.start(), m.group(0).lower()) for m in _CLUE_TOKEN.finditer(text)]
    starts = [pos for pos, _ in tokens]
    out = []
    for m in pattern.finditer(text):
        if any(k.start < m.end() and m.start() < k.end for k in keep):
            continue
        at = bisect.bisect_left(starts, m.start())
        near = {w for _, w in tokens[max(0, at - CLUE_DISTANCE):at + CLUE_DISTANCE + 1]}
        if len(near & clues[m.group(1).lower()]) >= min_clues:
            out.append(Span(m.start(), m.end()))
    return out


_QUOTED = re.compile(r"[\"“”«»„]([^\"“”«»„]{3,})[\"“”«»„]")
_REPORTED = re.compile(
    r"\b(he|she|they|someone|somebody|my \w+|this (guy|girl|kid|boy)|a (guy|girl|kid|boy))\s+"
    r"(told|tells|said|says|keeps saying|kept saying|wrote|writes|texted|texts|messaged|threatened|sent)\b"
    r"|\b(o|biri|birisi)\s+(bana\s+)?(dedi|diyor|yazdı|yazıyor|söyledi)\b", re.I)


def quoted(text: str, span: Span, previous: Span | None) -> bool:
    """A threat passed on ('he told me ...') or inside quotes: held for a moderator, not blocked."""
    for m in _QUOTED.finditer(text):
        if m.start(1) <= span.start + 1 and span.end <= m.end(1) + 1:
            return True
    if _REPORTED.search(text[span.start:span.end]):
        return True
    return bool(previous and _REPORTED.search(text[previous.start:previous.end]))


_LINK = re.compile(r"https?://|www\.", re.I)


def links(text: str) -> int:
    return len(_LINK.findall(text))


def repeats(text: str) -> tuple[tuple[int, float], ...]:
    """For the most repeated word, 2-word and 3-word phrase: how often it occurs and what share of the message's
    words it makes up ("follow me" x 8: 8 times, 1.0). The spam rule (decision.py) compares them with the
    platform's spam_tekrar_sayisi and spam_tekrar_orani."""
    words = [w.lower() for w in _WORD.findall(text)]
    out = []
    for n in (1, 2, 3):
        top = max(Counter(tuple(words[i:i + n]) for i in range(len(words) - n + 1)).values(), default=0)
        out.append((top, round(min(1.0, top * n / len(words)), 4) if words else 0.0))   # overlaps: "ha ha ha"
    return tuple(out)
