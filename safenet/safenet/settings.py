"""Platform settings from ayarlar.toml, merged by the team's ayarlar.py (varsayilan + profil + platform + kanal).

python -m safenet.settings prints what each platform ends up with.
"""
import tomllib
from functools import lru_cache

import ayarlar

CHANNEL_1TO1 = "birebir"   # a message with recipient_id
CHANNEL_GROUP = "grup"     # without: scored for the sender only, no x1.5


@lru_cache(maxsize=1)
def platforms() -> tuple[str, ...]:
    with open(ayarlar.DOSYA, "rb") as f:
        return tuple(tomllib.load(f).get("platform", {}))


@lru_cache(maxsize=64)
def for_platform(platform: str, channel: str = CHANNEL_1TO1) -> dict:
    """Raises ValueError for a platform without a [platform.<id>] block."""
    return ayarlar.ayarlar_yukle(platform, channel)


def public(platform: str) -> dict:
    """What GET /v1/settings shows: the merged thresholds and points, 1:1 channel."""
    a = for_platform(platform)
    return {k: a[k] for k in ("secim", "ad", "mesaj", "gizli_puan", "iliski", "kimlik", "karistirilabilir", "kanal") if k in a}


if __name__ == "__main__":
    for p in platforms():
        a = for_platform(p)
        print(f"{p}: profil={a['secim']['profil']}")
        for section in ("mesaj", "gizli_puan", "iliski", "kimlik"):
            print(f"  {section}: {a[section]}")
