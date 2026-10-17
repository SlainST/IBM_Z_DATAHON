"""The trained model files (models/model1.joblib, models/model2.joblib, made by train.py) and the explicit
threat rules in safenet/ml/models.py.

The model tests are skipped where the files are not there (laptops, CI). On the server, after training or
deploying a new pair:  .venv/bin/python -m pytest tests/test_models.py
The held-out sentences come from augment.py and were never trained on.
"""
import statistics
import time

import joblib
import pytest

import augment
import temizlik
from safenet import config
from safenet.engine.moderator import Moderator
from safenet.ml.models import CATEGORIES, CATEGORY, Models, explicit_threat
from safenet.state.store import MemoryStore

FILES = (config.MODELS_DIR / "model1.joblib", config.MODELS_DIR / "model2.joblib")
needs_models = pytest.mark.skipif(not all(f.exists() for f in FILES), reason="no trained model files in models/")
PDF_TEXT = "Great match yesterday Mark. But if you show up on Friday I'll f*cking break your legs."


@pytest.fixture(scope="module")
def trained():
    m = Models()
    m.model1, m.model2 = joblib.load(FILES[0]), joblib.load(FILES[1])
    return m


@pytest.fixture
def mod(trained):
    store = MemoryStore()
    store.open()
    yield Moderator(store, models=trained)
    store.close()


def harm(models, sentences):
    return list(models.model1.predict_proba([temizlik.temizle(s) for s in sentences])[:, 1])


@needs_models
def test_model1_contract(trained):
    assert [int(c) for c in trained.model1.classes_] == [0, 1]
    p = trained.model1.predict_proba(["see you tomorrow", "you are a worthless idiot"])
    assert p.shape == (2, 2) and ((p >= 0) & (p <= 1)).all()


@needs_models
def test_model2_predicts_api_categories(trained):
    labels = {CATEGORY.get(str(c), str(c)) for c in trained.model2.classes_}
    assert labels == set(CATEGORIES)


@needs_models
def test_one_call_is_fast(trained):
    times = []
    for _ in range(30):
        start = time.perf_counter()
        trained.model1.predict_proba(["hello there, see you after school"])
        times.append(time.perf_counter() - start)
    assert statistics.median(times) < 0.005          # ~0.5 ms on the LinuxONE server


@needs_models
def test_pdf_example_is_a_blocked_threat(mod):
    r = mod.check("demo_sosyal", {"sender_id": "a", "recipient_id": "b", "group_id": "g", "message_id": "m1",
                                  "text": PDF_TEXT})
    assert (r["decision"], r["reason"], r["category"]) == ("block", "threat", "threat")
    assert r["sender_standing"]["change"] == 48.0           # 40 threat + 5 fucking + 3 disguised


@needs_models
def test_identity_words_alone_are_not_harmful(trained):
    for word in augment.IDENTITIES_EVAL:
        neutral = harm(trained, [t.format(word) for t in augment.NEUTRAL_EVAL])
        assert statistics.mean(neutral) < 0.5, word
    everything = harm(trained, [t.format(w) for t in augment.NEUTRAL_EVAL for w in augment.IDENTITIES_EVAL])
    assert statistics.mean(everything) < 0.25


@needs_models
def test_attacks_on_identities_stay_harmful(trained):
    hateful = harm(trained, [t.format(w) for t in augment.HATEFUL_EVAL for w in augment.IDENTITIES_EVAL])
    assert statistics.mean(hateful) > 0.7


@needs_models
def test_look_alikes_are_not_blocked(mod):
    for i, text in enumerate(augment.HELDOUT_BENIGN + ["see you tomorrow", "we fed the ducks at the lake"]):
        r = mod.check("demo_sosyal", {"sender_id": f"s{i}", "recipient_id": "b", "text": text})
        assert r["decision"] != "block", text


@pytest.mark.parametrize("text", [
    "I'll f*cking break your legs", "i swear i will smash your face in", "you are dead meat",
    "i'm gonna beat the crap out of you", "i hope you die", "kys", "watch your back",
    "i'm going to hurt you after school"])
def test_explicit_threats(text):
    assert explicit_threat(temizlik.temizle(text))


@pytest.mark.parametrize("text", [
    "you are dead wrong", "you're dead on with that", "i'll shoot you an email", "i'll find you a seat",
    "break a leg tonight!", "i'm going to beat your high score", "kill the lights please", "you are dead to me"])
def test_not_explicit_threats(text):
    assert not explicit_threat(temizlik.temizle(text))
