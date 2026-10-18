"""The decision engine and points, on the memory store and (with SAFENET_TEST_DATABASE_URL) on Postgres."""
PDF_TEXT = "Great match yesterday Mark. But if you show up on Friday I'll f*cking break your legs."


def msg(uid, text, sender="a", recipient="b", group="g", message_id=None):
    body = {"sender_id": uid(sender), "group_id": uid(group), "text": text}
    if recipient:
        body["recipient_id"] = uid(recipient)
    if message_id:
        body["message_id"] = uid(message_id)
    return body


def test_pdf_example_threat(mod, uid):
    r = mod.check("demo_sosyal", msg(uid, PDF_TEXT, message_id="m1"))
    assert r["decision"] == "block" and r["recipient_sees"] is None
    assert r["reason"] == "threat" and r["category"] == "threat"
    assert r["worst_sentence"] == "But if you show up on Friday I'll f****** break your legs."
    assert r["hidden_profanity"] == [{"written": "f*cking", "word": "fucking"}]
    assert r["sender_standing"]["change"] == 48.0           # 40 threat + 5 fucking + 3 disguised
    assert r["sender_standing"]["level"] == "warned"
    assert r["suggested_action"] == "warn_sender"
    assert r["relation"] == {"blocked": True, "change": 48.0}
    assert "break your legs" in r["key_words"] and "fucking" in r["key_words"]
    assert r["harm"] >= 0.9 and r["wordless_harm"] >= 0.9


def test_retry_same_message_id_counts_once(mod, uid):
    first = mod.check("demo_sosyal", msg(uid, PDF_TEXT, message_id="m1"))
    again = mod.check("demo_sosyal", msg(uid, PDF_TEXT, message_id="m1"))
    assert again["replayed"] and not first["replayed"]
    assert again["decision"] == first["decision"] and again["worst_sentence"] == first["worst_sentence"]
    assert mod.store.user("demo_sosyal", uid("g"), uid("a"))["points"] == 48.0


def test_green_with_profanity_is_censored(mod, uid):
    r = mod.check("demo_sosyal", msg(uid, "f*ck, I missed the bus"))
    assert r["decision"] == "censor" and r["reason"] == "profanity"
    assert r["recipient_sees"] == "f***, I missed the bus"
    assert r["censored"] == [{"start": 0, "end": 4}]
    assert r["sender_standing"]["change"] == 9.0             # 6 + 3 disguised


def test_clean_message_allowed(mod, uid):
    r = mod.check("demo_sosyal", msg(uid, "see you tomorrow"))
    assert r["decision"] == "allow" and r["recipient_sees"] == "see you tomorrow"
    assert r["reason"] is None and r["worst_sentence"] is None and r["category"] is None
    assert r["sender_standing"] == {"level": "normal", "change": 0.0, "restrictions": 0, "restricted_until": None}


def test_yellow_held_on_school_censored_on_social(mod, uid):
    school = mod.check("demo_okul", msg(uid, "you are an idiot"))
    social = mod.check("demo_sosyal", msg(uid, "you are an idiot"))
    assert school["decision"] == "hold" and school["reason"] == "harmful"
    assert social["decision"] == "censor" and social["suggested_action"] == "warn_sender"
    assert social["category"] == "insult"


def test_targeted_hate_restricts_then_freezes(mod, uid):
    r = mod.check("demo_sosyal", msg(uid, "you dirty muslim"))
    assert r["decision"] == "block" and r["reason"] == "hate" and r["category"] == "religion"
    assert r["sender_standing"]["change"] == 70.0            # 25 blocked + 30 targeted x 1.5
    assert r["suggested_action"] == "restrict_sender"
    assert r["sender_standing"]["level"] == "restricted" and r["sender_standing"]["restricted_until"]
    nxt = mod.check("demo_sosyal", msg(uid, "see you tomorrow", recipient="c"))
    assert nxt["decision"] == "block" and nxt["reason"] == "sender_restricted"
    assert nxt["sender_standing"]["change"] == 0.0


def test_relation_block_only_towards_that_recipient(mod, uid):
    mod.check("demo_sosyal", msg(uid, PDF_TEXT))                           # A -> B reaches 48
    to_b = mod.check("demo_sosyal", msg(uid, "see you tomorrow", group="other"))
    to_c = mod.check("demo_sosyal", msg(uid, "see you tomorrow", recipient="c", group="other"))
    assert to_b["decision"] == "block" and to_b["reason"] == "relation_blocked"
    assert to_c["decision"] == "allow"


def test_possible_typo_adds_no_points(mod, uid):
    r = mod.check("demo_sosyal", msg(uid, "I fed the fuck at the lake"))
    assert r["possible_typos"] == [{"word": "fuck", "suggestion": "duck"}]
    assert r["recipient_sees"] == "I fed the f*** at the lake"
    assert r["sender_standing"]["change"] == 0.0


def test_quoted_threat_is_held(mod, uid):
    r = mod.check("demo_okul", msg(uid, 'He told me "I will kill you tomorrow".'))
    assert r["decision"] == "hold" and r["reason"] == "quoted_threat"


def test_game_words_free_only_in_game_context(mod, uid):
    """oyun_dili_serbest frees "kill" when the message has one of its clues ("gg", "round"); a threat without
    them is judged like on any platform (docs/DECISION_ENGINE.md, choice 9a)."""
    game = mod.check("demo_oyun", msg(uid, "gg, I will kill you next round"))
    social = mod.check("demo_sosyal", msg(uid, "gg, I will kill you next round"))
    assert game["decision"] == "allow"
    assert social["decision"] == "block" and social["reason"] == "threat"
    real = mod.check("demo_oyun", msg(uid, "I will kill you and your whole family", sender="c"))
    assert real["decision"] == "block" and real["reason"] == "threat"
    fire = mod.check("demo_oyun", msg(uid, "I hope you die in a fire", sender="d"))
    assert fire["decision"] == "block" and fire["reason"] == "threat"


def test_a_listed_phrase_is_never_a_game_word(mod, uid):
    """"kill" is a game word and "game" is its clue, but in "kill yourself" it is part of a listed phrase."""
    r = mod.check("demo_oyun", msg(uid, "gg noob, you are so bad at this game, go kill yourself"))
    assert (r["decision"], r["reason"]) == ("block", "threat") and "kill yourself" in r["key_words"]


def test_written_out_kill_yourself_is_starred_like_kys(mod, uid):
    r = mod.check("demo_oyun", msg(uid, "just kill yourself, loser"))
    assert r["decision"] == "block" and r["reason"] == "threat"
    assert r["censored"] == [{"start": 5, "end": 18}] and r["hidden_profanity"] == []
    assert "kill yourself" in r["key_words"]


def test_repeated_phrase_is_spam(mod, uid):
    r = mod.check("demo_sosyal", msg(uid, " ".join(["follow me"] * 8)))
    assert r["decision"] == "block" and r["reason"] == "spam"


def test_severe_bullying_is_red_without_any_listed_word(mod, uid):
    r = mod.check("demo_sosyal", msg(uid, "nobody likes you, just leave the group chat"))
    assert (r["decision"], r["reason"], r["category"]) == ("block", "very_harmful", "insult")
    assert r["key_words"][0] == "nobody likes you"


def test_plain_insults_stay_yellow(mod, uid):
    r = mod.check("demo_sosyal", msg(uid, "you are a stupid ugly loser"))
    assert (r["decision"], r["reason"], r["category"]) == ("censor", "harmful", "insult")
    assert r["harm"] <= 0.72


def test_reported_bullying_is_not_red(mod, uid):
    r = mod.check("demo_okul", msg(uid, 'she told me "nobody likes you" in front of everyone'))
    assert r["decision"] != "block"


def test_sexual_request_xenophobia_and_blackmail_are_red(mod, uid):
    sexual = mod.check("demo_sosyal", msg(uid, "send me a pic of you in your underwear"))
    assert (sexual["decision"], sexual["reason"], sexual["category"]) == ("block", "very_harmful", "sexual")
    hate = mod.check("demo_sosyal", msg(uid, "go back to your country", sender="c"))
    assert (hate["decision"], hate["reason"], hate["category"]) == ("block", "hate", "race")
    blackmail = mod.check("demo_sosyal", msg(uid, "send me your address or I'll post your pics everywhere", sender="d"))
    assert (blackmail["decision"], blackmail["reason"]) == ("block", "threat")


def test_spaced_and_lookalike_profanity(mod, uid):
    r = mod.check("demo_sosyal", msg(uid, "what the f u c k is this, my friend"))
    assert {"written": "f u c k", "word": "fuck"} in r["hidden_profanity"]
    assert "f * * *" in r["recipient_sees"]


def test_short_profane_message_hits_ratio_rule(mod, uid):
    r = mod.check("demo_sosyal", msg(uid, "this is shit"))
    assert r["decision"] == "block" and r["reason"] == "profanity_ratio"


def test_recovery_needs_clean_history(mod, uid):
    mod.check("demo_sosyal", msg(uid, "you are an idiot"))                 # +10
    points = lambda: mod.store.user("demo_sosyal", uid("g"), uid("a"))["points"]
    start = points()
    for _ in range(7):
        mod.check("demo_sosyal", msg(uid, "nice game today"))
    assert points() == start                                              # only 7 clean so far: no recovery yet
    mod.check("demo_sosyal", msg(uid, "nice game today"))
    assert points() < start


def test_stats_and_groups(mod, uid):
    mod.check("demo_sosyal", msg(uid, PDF_TEXT))
    mod.check("demo_sosyal", msg(uid, "see you tomorrow", recipient="c"))
    if hasattr(mod.store, "_flush"):
        mod.store._flush()
    g = mod.store.stats("demo_sosyal", uid("g"))
    assert g["messages"] == 2 and g["harmful"] == 1 and g["decisions"]["block"] == 1
    assert any(row["group"] == uid("g") for row in mod.store.groups("demo_sosyal", 500))


def test_parallel_messages_from_one_sender_all_count(mod, uid):
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(5) as pool:
        list(pool.map(lambda i: mod.check("demo_sosyal", msg(uid, "f*ck, I missed the bus", recipient=f"r{i}")), range(5)))
    assert mod.store.user("demo_sosyal", uid("g"), uid("a"))["points"] == 45.0


class _WholeOnly:
    """Model 1 that finds harm only in the whole message, never in one of its short sentences."""
    classes_ = [0, 1]

    def predict_proba(self, texts):
        import numpy as np
        return np.array([[0.4, 0.6] if len(t) > 20 else [0.9, 0.1] for t in texts])


class _Insult:
    def predict(self, texts):
        return ["insult"] * len(texts)


def test_harm_spread_over_sentences_is_yellow_never_red(store, uid):
    from safenet.engine.moderator import Moderator
    from safenet.ml.models import Models
    models = Models()
    models.model1, models.model2 = _WholeOnly(), _Insult()
    mod = Moderator(store, models=models)
    r = mod.check("demo_sosyal", msg(uid, "you blocked me. you worm."))
    assert (r["decision"], r["reason"], r["category"]) == ("censor", "harmful", "insult")
    assert (r["harm"], r["wordless_harm"]) == (0.6, 0.1)
    assert mod.check("demo_okul", msg(uid, "you blocked me. you worm.", sender="c"))["decision"] == "hold"
    # a victim's report is judged sentence by sentence only
    assert mod.check("demo_sosyal", msg(uid, "he said i am a worm. i cried.", sender="d"))["decision"] == "allow"
