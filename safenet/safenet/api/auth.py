"""X-API-Key -> platform. config/api_keys.toml holds only sha256(key) = "platform" (scripts/new_api_key.py)."""
import hashlib
import tomllib

from fastapi import Header, HTTPException

from .. import config, settings


def _load() -> dict[str, str]:
    if not config.API_KEYS_FILE.exists():
        return {}
    with open(config.API_KEYS_FILE, "rb") as f:
        return dict(tomllib.load(f).get("keys", {}))


KEYS = _load()


def platform_for(key: str | None) -> str:
    if not key:
        raise HTTPException(401, "X-API-Key missing")
    platform = KEYS.get(hashlib.sha256(key.encode()).hexdigest())
    if platform is None and config.DEV_KEYS and key.startswith("dev-"):
        platform = key[4:]
    if platform is None:
        raise HTTPException(401, "unknown API key")
    if platform not in settings.platforms():
        raise HTTPException(403, f"platform {platform!r} has no [platform.{platform}] block in ayarlar.toml")
    return platform


def require_platform(x_api_key: str | None = Header(default=None)) -> str:
    return platform_for(x_api_key)
