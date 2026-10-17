"""Make an API key for one platform: python scripts/new_api_key.py demo_okul

Prints the key once. Only its SHA-256 goes into config/api_keys.toml (chmod 600, gitignored);
put the key itself in that platform's config.py. Revoke: delete its line, restart the API.
"""
import hashlib
import os
import secrets
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
KEYS = ROOT / "config" / "api_keys.toml"
SETTINGS = [ROOT / "config" / "ayarlar.toml", ROOT / "ayarlar.toml"]


def platforms() -> set[str] | None:
    for path in SETTINGS:
        if path.exists():
            return set(tomllib.loads(path.read_text(encoding="utf-8")).get("platform", {}))
    return None


def main() -> None:
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    platform = sys.argv[1]
    known = platforms()
    if known is not None and platform not in known:
        sys.exit(f"unknown platform {platform!r}; ayarlar.toml has: {', '.join(sorted(known))}")

    key = f"sn_{platform}_{secrets.token_urlsafe(32)}"
    digest = hashlib.sha256(key.encode()).hexdigest()

    KEYS.parent.mkdir(exist_ok=True)
    new = not KEYS.exists()
    fd = os.open(KEYS, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    with os.fdopen(fd, "a", encoding="utf-8") as f:
        if new:
            f.write("# sha256(key) = platform. The keys themselves live only in each platform's config.\n[keys]\n")
        f.write(f'"{digest}" = "{platform}"\n')
    os.chmod(KEYS, 0o600)

    print(f"platform: {platform}")
    print(f"key:      {key}")
    print("Shown once. Put it in this platform's config.py; never commit it.")


if __name__ == "__main__":
    main()
