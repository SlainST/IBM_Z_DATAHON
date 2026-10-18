"""SAFENET_* environment settings. Every one is listed, with comments, in deploy/linuxone/safenet.env.example."""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _int(name: str, default: int) -> int:
    return int(os.getenv(name, default))


MAX_TEXT_LEN = _int("SAFENET_MAX_TEXT_LEN", 2000)
MAX_BATCH = _int("SAFENET_MAX_BATCH", 100)
DATABASE_URL = os.getenv("SAFENET_DATABASE_URL", "")
DB_POOL_SIZE = _int("SAFENET_DB_POOL_SIZE", 5)
DB_TIMEOUT_S = float(os.getenv("SAFENET_DB_TIMEOUT_S", "2"))
DEV_KEYS = os.getenv("SAFENET_DEV_KEYS", "0") == "1"
API_KEYS_FILE = Path(os.getenv("SAFENET_API_KEYS", ROOT / "config" / "api_keys.toml"))
MODELS_DIR = Path(os.getenv("SAFENET_MODELS_DIR", ROOT / "models"))
ANALYSIS_CACHE = _int("SAFENET_ANALYSIS_CACHE", 4096)
