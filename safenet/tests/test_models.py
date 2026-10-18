"""The trained model files (models/model1.joblib, models/model2.joblib, made by train.py).

The model tests are skipped where the files are not there (laptops, CI) or were trained on a machine with the
other byte order (the hashed features differ: safenet/ml/models.py). On the server, after training or deploying
a new pair:  .venv/bin/python -m pytest tests/test_models.py
The held-out sentences come from augment.py and were never trained on. The phrase rules are in test_rules.py.
"""
import json
import statistics
import sys
import time

import joblib
import pytest

import augment
import temizlik
from safenet import config
from safenet.engine.moderator import Moderator
from safenet.ml import models as ml
from safenet.ml.models import CATEGORIES, CATEGORY, Models
from safenet.state.store import MemoryStore

FILES = (config.MODELS_DIR / "model1.joblib", config.MODELS_DIR / "model2.joblib")
INFO = config.MODELS_DIR / ml.INFO


def _usable() -> tuple[bool, str]:
    if not all(f.exists() for f in FILES):
        return False, "no trained model files in models/"
    trained_on = json.loads(INFO.read_text(encoding="utf-8")).get("byteorder") if INFO.exists() else None
    if trained_on and trained_on != sys.byteorder:
        return False, f"models/ was trained on a {trained_on}-endian machine, this one is {sys.byteorder}-endian"
    return True, ""


needs_models = pytest.mark.skipif(not _usable()[0], reason=_usable()[1])
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


def _dummy_pair(folder, byteorder):
    joblib.dump({"stand-in": 1}, folder / "model1.joblib")
    joblib.dump({"stand-in": 2}, folder / "model2.joblib")
    (folder / ml.INFO).write_text(json.dumps({"byteorder": byteorder, "trained": "2026-10-18T05:00:00",
                                              "machine": "s390x", "sklearn": "1.4.1.post1"}), encoding="utf-8")


def test_a_pair_from_the_other_byte_order_is_not_used(tmp_path, monkeypatch):
    monkeypatch.setattr(ml, "MODELS_DIR", tmp_path)
    _dummy_pair(tmp_path, "big" if sys.byteorder == "little" else "little")
    assert Models().status() == {"model1": "fallback", "model2": "fallback"}
    assert Models().version() is None


def test_a_pair_from_this_byte_order_is_loaded(tmp_path, monkeypatch):
    monkeypatch.setattr(ml, "MODELS_DIR", tmp_path)
    _dummy_pair(tmp_path, sys.byteorder)
    m = Models()
    assert m.status() == {"model1": "loaded", "model2": "loaded"}
    assert m.version() == {"trained": "2026-10-18T05:00:00", "machine": "s390x", "byteorder": sys.byteorder,
                           "sklearn": "1.4.1.post1"}
