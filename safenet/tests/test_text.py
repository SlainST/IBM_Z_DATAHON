"""safenet/pipeline: game words in context, spam, listed phrases written out."""
import pytest

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
