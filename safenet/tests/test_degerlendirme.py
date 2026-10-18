"""The evaluation set (degerlendirme_seti.csv): well formed, and every demo platform has all four decisions.

Whether the engine agrees with it is a report, not a test: python degerlendir.py
"""
from degerlendir import KARARLAR, PLATFORMLAR, oku
from safenet import config, settings
from safenet.ml.models import CATEGORIES

REASONS = {"threat", "hate", "very_harmful", "profanity_ratio", "spam", "quoted_threat", "harmful", "profanity"}


def test_set_is_well_formed():
    rows = oku()
    assert len({r["id"] for r in rows}) == len(rows)
    assert set(PLATFORMLAR) <= set(settings.platforms())
    for r in rows:
        assert 0 < len(r["metin"].strip()) <= config.MAX_TEXT_LEN, r["id"]
        assert all(r[p] in KARARLAR for p in PLATFORMLAR), r["id"]
        assert r["zarar"] in {"yok", "orta", "yuksek"}, r["id"]
        assert r["kategori"] in set(CATEGORIES) | {""}, r["id"]
        assert r["neden"] in REASONS | {""}, r["id"]


def test_every_platform_has_every_decision():
    rows = oku()
    for p in PLATFORMLAR:
        assert {r[p] for r in rows} == set(KARARLAR), p
