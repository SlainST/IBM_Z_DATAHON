"""Age-based moderation profiles, like Roblox's under-13 / 13+ / 17+ chat settings."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Profile:
    name: str
    mask_severity: int     # lexicon hits at or above this are masked with ###
    block_severity: int    # lexicon hits at or above this block the whole message
    block_score: float     # ML score at or above this blocks the message
    review_score: float    # ML score at or above this flags the message for human review
    mask_pii: bool


PROFILES = {
    "under13": Profile("under13", mask_severity=1, block_severity=2, block_score=0.80, review_score=0.50, mask_pii=True),
    "teen": Profile("teen", mask_severity=1, block_severity=3, block_score=0.90, review_score=0.60, mask_pii=True),
    "adult": Profile("adult", mask_severity=2, block_severity=3, block_score=0.95, review_score=0.70, mask_pii=False),
}
