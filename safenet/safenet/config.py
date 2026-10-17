import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

LEXICON_DIR = Path(os.getenv("SAFENET_LEXICON_DIR", ROOT / "data" / "lexicon"))
MODEL_PATH = Path(os.getenv("SAFENET_MODEL_PATH", ROOT / "models" / "toxicity.joblib"))
DEFAULT_PROFILE = os.getenv("SAFENET_DEFAULT_PROFILE", "teen")
MAX_TEXT_LEN = int(os.getenv("SAFENET_MAX_TEXT_LEN", "2000"))
