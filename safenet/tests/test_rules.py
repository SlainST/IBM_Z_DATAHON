"""The text rules around the models: listed phrases, game words in context, spam, and the analysis cache
(DECISION_ENGINE choices 9, 10 and 16)."""
from safenet import settings
from safenet.engine.analysis import Analyzer
from safenet.engine.decision import is_spam
from safenet.ml.models import Models
from safenet.pipeline import profanity


def msg(uid, text, sender="a"):
    return {"sender_id": uid(sender), "recipient_id": uid("b"), "group_id": uid("g"), "text": text}


def test_written_out_phrase_is_found_like_its_short_form():
    for text in ("kill yourself", "just kill urself!", "KILL YOUR SELF"):
        [hit] = profanity.find(text)
        assert hit.word == "kill yourself" and not hit.hidden, text
    assert profanity.star("kill yourself", profanity.find("kill yourself")) == "k*** ********"
    assert [h.word for h in profanity.find("shut the fuck up")] == ["fuck"]    # its own word is listed
    assert profanity.find("that skill yourselfie") == []


def test_written_out_phrase_is_blocked_everywhere(mod, uid):
    for platform in ("demo_sosyal", "demo_okul", "demo_oyun"):
        r = mod.check(platform, msg(uid, "you should kill yourself, loser"))
        assert r["decision"] == "block" and r["reason"] == "threat", platform
        assert "kill yourself" in r["key_words"]


def test_game_words_free_only_in_game_context(mod, uid):
    def decision(text):
        return mod.check("demo_oyun", msg(uid, text))["decision"]

    assert decision("that boss fight killed me so many times") == "allow"
    assert decision("nice round! I'll kill you next time") == "allow"      # the clue is in the sentence before
    assert decision("I'm dead 😂 that joke") == "allow"                     # an emoji clue
    assert decision("I hope you die in a fire") == "block"
    assert decision("you are dead after school") == "block"
    assert decision("I will kill you and your whole family") == "block"
    assert decision("gg, kill yourself") == "block"                         # a listed phrase is never a game word


def test_repeated_phrase_is_spam(mod, uid):
    r = mod.check("demo_sosyal", msg(uid, "follow me " * 8))
    assert r["decision"] == "block" and r["reason"] == "spam"
    assert mod.check("demo_sosyal", msg(uid, "follow me " * 3))["decision"] == "allow"
    assert mod.check("demo_sosyal", msg(uid, "lol " * 10))["reason"] == "spam"


def test_spam_numbers_come_from_settings():
    analysis = Analyzer(Models())._analyze("buy now " * 5, False, 1, True)
    m = dict(settings.for_platform("demo_sosyal")["mesaj"])
    assert not is_spam(analysis, m)
    m["spam_tekrar_sayisi"] = 5
    assert is_spam(analysis, m)


def test_analysis_cache_keeps_no_text(mod, uid):
    text = "Meet me behind the gym at seven, you stupid idiot. I mean it."
    first = mod.check("demo_sosyal", msg(uid, text))
    again = mod.check("demo_sosyal", msg(uid, text, sender="c"))           # answered from the cache
    cached = list(mod.analyzer._cache.values())
    assert cached and all("behind the gym" not in repr(a) for a in cached)
    assert again["worst_sentence"] == first["worst_sentence"] and "behind the gym" in first["worst_sentence"]
