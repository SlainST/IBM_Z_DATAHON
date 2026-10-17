"""PDF step 8a: the colour of each sentence, the worst one deciding for the message, and the decision.

RED    threat and harm >= tehdit_esigi; race / religion / gender and wordless >= nefret_esigi;
       wordless >= cok_kotu_esigi; spam; or more than spam_kufur_orani of the words are listed profanity
YELLOW harm >= sari_esigi
GREEN  everything else
"""
from dataclasses import dataclass

from .analysis import Analysis, Sentence

HATE = {"race", "religion", "gender"}
RED_ORDER = ("threat", "hate", "very_harmful", "spam", "profanity_ratio")   # which red reason wins


@dataclass
class Verdict:
    colour: str                   # green | yellow | red
    decision: str                 # allow | censor | hold | block
    reason: str | None
    worst: int | None             # index of the deciding sentence
    quoted: bool                  # a quoted threat: held, no colour points
    counted_hits: list            # listed words that score (likely typos excluded)
    clean: bool                   # green and no listed word: counts towards recovery


def _red_reason(s: Sentence, m: dict) -> str | None:
    if s.category == "threat" and s.harm >= m["tehdit_esigi"]:
        return "threat"
    if s.category in HATE and s.wordless >= m["nefret_esigi"]:
        return "hate"
    if s.wordless >= m["cok_kotu_esigi"]:
        return "very_harmful"
    return None


def counted_hits(analysis: Analysis) -> list:
    out = []
    for s in analysis.sentences:
        typos = {t["word"] for t in s.typos}
        out += [h for h in s.hits if h.word not in typos]
    return out


def judge(analysis: Analysis, a: dict) -> Verdict:
    m = a["mesaj"]
    hits = counted_hits(analysis)

    reds = [(RED_ORDER.index(r), -s.harm, i) for i, s in enumerate(analysis.sentences) if (r := _red_reason(s, m))]
    message_red = None
    if analysis.spam:
        message_red = "spam"
    elif len(hits) / analysis.words > m["spam_kufur_orani"]:
        message_red = "profanity_ratio"
    if message_red:
        reds.append((RED_ORDER.index(message_red), 0.0, _most_profane(analysis)))

    if reds:
        rank, _, i = min(reds)
        reason = RED_ORDER[rank]
        s = analysis.sentences[i]
        if reason == "threat" and s.quoted and not message_red:
            return Verdict("red", "hold", "quoted_threat", i, True, hits, False)
        return Verdict("red", "block", reason, i, False, hits, False)

    yellow = [(-s.harm, i) for i, s in enumerate(analysis.sentences) if s.harm >= m["sari_esigi"]]
    if yellow:
        i = min(yellow)[1]
        decision = "hold" if m["sari_davranis"] == "beklet" else "censor"
        return Verdict("yellow", decision, "harmful", i, False, hits, False)

    if analysis.hits:
        return Verdict("green", "censor", "profanity", _most_profane(analysis), False, hits, not hits)
    return Verdict("green", "allow", None, None, False, hits, True)


def _most_profane(analysis: Analysis) -> int:
    return max(range(len(analysis.sentences)), key=lambda i: (len(analysis.sentences[i].hits), analysis.sentences[i].harm))
