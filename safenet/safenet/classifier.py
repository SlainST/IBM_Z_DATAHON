"""ML toxicity score: catches toxic messages that use no listed word.

The model is a scikit-learn pipeline (char n-gram TF-IDF + logistic regression)
trained by scripts/train.py. It runs in well under a millisecond per message on
CPU, which keeps the API real-time without a GPU.
"""

import logging
from pathlib import Path

import joblib

from .normalize import normalized_text

log = logging.getLogger(__name__)


class ToxicityClassifier:
    def __init__(self, model_path: Path):
        self.model = None
        if model_path.exists():
            self.model = joblib.load(model_path)
        else:
            log.warning("No model at %s; running lexicon-only. Train one with scripts/train.py.", model_path)

    @property
    def available(self) -> bool:
        return self.model is not None

    def score(self, text: str) -> float | None:
        if self.model is None:
            return None
        return float(self.model.predict_proba([normalized_text(text)])[0][1])
