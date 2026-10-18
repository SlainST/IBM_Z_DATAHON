"""safenet/pipeline: game words in context, spam, listed phrases written out, what the models read."""
import pytest

import temizlik
from safenet.pipeline import profanity, text as tx


@pytest.mark.parametrize("message, freed", [
    ("gg, I will kill you next round", True),
    ("that boss fight killed me so many times", True),
    ("I'm dead 😂 that joke is hilarious", True),
    ("I will kill you and your whole family", False),
    ("you are dead after school", False),
])
def test_game_words_need_their_context(message, freed):
    sentence = message.split(",")[-1]
    assert (tx.without_game_words(sentence, message) != sentence) is freed


def test_a_clue_elsewhere_in_the_message_counts():
    assert "kill" not in tx.without_game_words("I will kill you next time", "gg! I will kill you next time")


@pytest.mark.parametrize("message, is_spam", [
    ("lol " * 10, True),
    ("follow me " * 8, True),
    ("free robux http://a.io http://b.io http://c.io", True),
    ("check out my new video https://youtube.com/watch?v=abc123", False),
    ("follow me follow me please", False),
    ("the cat and the dog and the bird and the fish went to the park with the kids", False),
])
def test_spam(message, is_spam):
    assert tx.spam(message) is is_spam


@pytest.mark.parametrize("message, written", [
    ("just kill yourself", "kill yourself"),
    ("KILL URSELF", "KILL URSELF"),
    ("kill your self", "kill your self"),
])
def test_listed_phrase_written_out(message, written):
    hits = profanity.find(message)
    assert [(h.written, h.word, h.severity, h.hidden) for h in hits] == [(written, "kill yourself", 10, False)]


def test_phrases_with_a_listed_word_are_found_through_the_word():
    assert [h.word for h in profanity.find("what the fuck")] == ["fuck"]
    assert "what the fuck" not in {p for _, p in profanity.phrases()}


@pytest.mark.parametrize("clean, read", [
    ("the kids began to snigger at the joke.", "the kids began to at the joke."),   # a slur's letters inside
    ("a raccoon got into the trash", "a got into the trash"),
    ("our class went on a field trip", "our class went on a field trip"),         # "ass" inside: not a slur
    ("you are a nigger", "you are a nigger"),                                     # the slur itself stays
])
def test_models_do_not_read_words_that_carry_a_slur(clean, read):
    assert tx.for_models(clean) == read


@pytest.mark.parametrize("message, words", [
    ("f u c k you", ["fuck"]),
    ("a f u c k", ["fuck"]),                 # a short word in front
    ("s h i t s", ["shits"]),
    ("go to h e l l", ["hell"]),
    ("h e l l o everyone", []),              # "hell" + "o" is hello
    ("c l a s s starts now", []),            # "cl" + "ass"
    ("a s s i g n m e n t", []),
])
def test_spaced_letters_only_when_the_rest_are_words(message, words):
    assert [h.word for h in profanity.find(message)] == words
    assert all(w in temizlik.temizle(message) for w in words)


@pytest.mark.parametrize("message, n", [("🖕", 1), ("you 🖕🏽", 1), ("🖕🖕🖕", 1), ("you are a 💩", 0)])
def test_listed_emoji(message, n):
    hits = profanity.find(message)
    assert len(hits) == n and all(h.word == "fuck" and h.hidden for h in hits)
    if n:
        assert profanity.word_count(message, hits) == len(message.split())


def test_spam_numbers_are_the_platforms_settings():
    """The cached analysis keeps counts, not the text; ayarlar.toml's numbers decide (spam_tekrar_sayisi)."""
    from safenet.engine.analysis import Analyzer
    from safenet.engine.decision import is_spam
    from safenet.ml.models import Models
    a = Analyzer(Models())._analyze("follow me " * 8, False, 1, True)
    m = {"spam_link_sayisi": 3, "spam_tekrar_sayisi": 8, "spam_tekrar_orani": 0.6}
    assert is_spam(a, m) and not is_spam(a, m | {"spam_tekrar_sayisi": 9})
    assert not any(isinstance(v, str) for v in vars(a).values())
