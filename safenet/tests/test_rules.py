"""safenet/ml/rules.py: the phrase rules on top of the models. No model files needed.

Each kind has sentences it must catch and look-alikes it must leave alone; the look-alikes are the ones that
made a broader pattern wrong on the training data (models/README.md, "Rules").
"""
import pytest

import kimlik
import temizlik
from safenet.ml import rules


def kind(text: str) -> str | None:
    found = rules.find(temizlik.temizle(text))
    return found.rule.kind if found else None


@pytest.mark.parametrize("text, expected", [
    ("I'll f*cking break your legs", "threat"),
    ("i swear i will smash your face in", "threat"),
    ("you are dead meat", "threat"),
    ("i'm gonna beat the crap out of you", "threat"),
    ("I'm going to find you and beat you up", "threat"),
    ("i'll mess you up after school", "threat"),
    ("i hope you die", "threat"),
    ("watch your back", "threat"),
    ("i'm going to hurt you after school", "threat"),
    ("kys", "self_harm"),
    ("you should just die", "self_harm"),
    ("send me your address or I'll post your pics everywhere", "blackmail"),
    ("do it or i'll tell everyone at school", "blackmail"),
    ("nobody likes you", "bullying"),
    ("you're worthless and everyone knows it", "bullying"),
    ("everyone would be happier if you just disappeared", "bullying"),
    ("send nudes", "sexual"),
    ("send me a pic of you in your underwear", "sexual"),
    ("go back to your country", "xenophobia"),
    ("go back to China you chink", "xenophobia"),
    ("all immigrants are criminals", "dehumanizing"),
    ("muslims should be deported", "dehumanizing"),
])
def test_catches(text, expected):
    assert kind(text) == expected


@pytest.mark.parametrize("text", [
    "you are dead wrong", "you're dead on with that", "i'll shoot you an email", "i'll find you a seat",
    "break a leg tonight!", "i'm going to beat your high score", "kill the lights please", "you are dead to me",
    "i will never hurt you", "i'm not going to kill you", "we had a drop dead gorgeous view",
    "it would be better if you explained the change", "go back to your room", "i want to go back to china next year",
    "not all muslims are terrorists", "send me a pic of you in paris", "clean your room or i'll tell mom",
    "i'm going to kill it at the exam tomorrow",
])
def test_leaves_alone(text):
    assert kind(text) is None


def test_categories_and_floors():
    assert rules.find("i will kill you").rule.category == "threat"
    assert rules.find("all immigrants are criminals").rule.category == "race"
    assert rules.find("women are inferior").rule.category == "gender"
    assert rules.find("nobody likes you").rule.floor == rules.SEVERE_FLOOR
    assert rules.find("kys").rule.floor == rules.THREAT_FLOOR
    assert rules.explicit_threat("i will kill you") and not rules.explicit_threat("nobody likes you")


def test_identity_attack():
    assert rules.identity_attack({"bicim": "hedefli", "hakaret_kelimesi": False})
    assert rules.identity_attack({"bicim": None, "hakaret_kelimesi": True})
    assert not rules.identity_attack({"bicim": "bahsetme", "hakaret_kelimesi": False})


@pytest.mark.parametrize("text, mention", [
    ("i'm gay i love men", True),
    ("she is the first black woman to win that award", True),
    ("my best friend is gay", True),
    ("i hate muslims", False),             # a hostile word
    ("you muslim", False),                 # the identity as a label for the reader
    ("you're such a girl", False),
    ("muslims are everywhere", False),     # a claim about the whole group
    ("that's so gay", False),              # pejorative use
    ("see you tomorrow", False),           # no identity at all
])
def test_identity_mentions(text, mention):
    clean = temizlik.temizle(text)
    assert rules.mention_only(clean, kimlik.kimlik_analizi(clean), has_listed_words=False) is mention


def test_a_listed_word_keeps_the_identity_in_the_score():
    clean = temizlik.temizle("fucking gays everywhere")
    assert not rules.mention_only(clean, kimlik.kimlik_analizi(clean), has_listed_words=True)


def test_without_identity():
    assert rules.without_identity("she is the first black woman to win") == "she is the first to win"
    assert rules.without_identity("i'm gay and i love men") == "i'm and i love men"


@pytest.mark.parametrize("text, addressed, take", [
    ("racism has no place in sports", False, (False, True)),
    ("i was bullied at school today", False, (False, True)),
    ("you are a racist", True, (False, False)),                     # aimed at the reader: scored as it is
    ("islam is a religion of bigotry", False, (False, False)),      # an identity that may be attacked
    ("i'm gay and i hate homophobia", False, (False, False)),       # "hate" keeps the identity's part
    ("my gay friend was bullied", False, (True, True)),
    ("see you tomorrow", True, (False, False)),
    ("i'm not sexist but women just shouldn't be announcers", False, (False, False)),   # the disclaimer
    ("call me racist, but racism isn't real", False, (False, False)),
])
def test_what_a_sentence_only_mentions(text, addressed, take):
    clean = temizlik.temizle(text)
    assert rules.mentions(clean, kimlik.kimlik_analizi(clean), False, addressed) == take


def test_nothing_is_taken_out_next_to_a_listed_word():
    clean = temizlik.temizle("fuck racism")
    assert rules.mentions(clean, kimlik.kimlik_analizi(clean), True, False) == (False, False)
    assert rules.without("my gay friend was bullied", True, True) == "my friend was"
