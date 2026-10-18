"""Request and response bodies (docs/API.md). Unknown request fields are refused with 422.

The response models document the answers: they are shown on /docs and exported to schemas/*.schema.json
(scripts/export_schemas.py), and tests/test_api.py checks every kind of answer against them. The endpoints return
plain dicts, so the models cost nothing per request.
"""
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from .. import config

ID = r"^[^/\x00-\x1f\x7f]+$"   # 1-128 characters, any UTF-8 except / and control characters

Decision = Literal["allow", "censor", "hold", "block"]
Reason = Literal["threat", "hate", "very_harmful", "profanity_ratio", "spam", "quoted_threat", "harmful", "profanity",
                 "sender_restricted", "relation_blocked"]
Category = Literal["insult", "gender", "religion", "race", "sexual", "threat"]
Level = Literal["normal", "warned", "restricted"]


# ---- requests ------------------------------------------------------------------------------------------------
class CheckRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sender_id: str = Field(min_length=1, max_length=128, pattern=ID)
    text: str = Field(min_length=1, max_length=config.MAX_TEXT_LEN)
    recipient_id: str | None = Field(default=None, min_length=1, max_length=128, pattern=ID)
    group_id: str = Field(default="general", min_length=1, max_length=128, pattern=ID)
    message_id: str | None = Field(default=None, min_length=1, max_length=128, pattern=ID)


class BatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    messages: list[CheckRequest] = Field(min_length=1, max_length=config.MAX_BATCH)


# ---- responses -----------------------------------------------------------------------------------------------
class Span(BaseModel):
    start: int = Field(description="index in `text` of the first starred character (Python string index)")
    end: int


class HiddenWord(BaseModel):
    written: str = Field(description='as written: "f*cking", "sh1t", "f u c k"')
    word: str = Field(description="the listed word it stands for")


class PossibleTypo(BaseModel):
    word: str = Field(description="the listed word found")
    suggestion: str = Field(description='the innocent word probably meant: "duck"')


class SenderStanding(BaseModel):
    level: Level
    change: float = Field(description="what this message did to the hidden points; negative when a clean message "
                                      "lowered them")
    restrictions: int = Field(description="how many times this sender has been restricted in this group")
    restricted_until: str | None = Field(description="ISO 8601, while the sender is restricted")


class RelationStanding(BaseModel):
    blocked: bool = Field(description="this sender's messages no longer reach this recipient")
    change: float


class CheckResponse(BaseModel):
    key: str = Field(description='"platform/group/sender": the row whose points changed')
    platform: str
    group: str
    sender: str
    recipient: str | None
    message_id: str | None
    decision: Decision
    recipient_sees: str | None = Field(description="the text for allow, the starred text for censor, null otherwise")
    reason: Reason | None
    worst_sentence: str | None = Field(description="the sentence that decided, starred; null when allowed")
    harm: float = Field(ge=0, le=1, description="harm score of the worst sentence")
    wordless_harm: float = Field(ge=0, le=1, description="the same sentence without its listed words")
    category: Category | None = Field(description="only for yellow and red messages")
    key_words: list[str]
    censored: list[Span]
    hidden_profanity: list[HiddenWord]
    possible_typos: list[PossibleTypo]
    sender_standing: SenderStanding
    relation: RelationStanding | None = Field(description="null without recipient_id")
    suggested_action: Literal["warn_sender", "restrict_sender"] | None
    replayed: bool = Field(description="this message_id was answered before: the stored decision, nothing counted")
    latency_ms: float


class BatchResponse(BaseModel):
    results: list[CheckResponse]


class UserView(BaseModel):
    key: str
    points: float
    level: Level
    recent_clean: int
    recent_messages: int
    restrictions: int
    restricted_until: str | None
    messages: int


class RelationView(BaseModel):
    platform: str
    sender: str
    recipient: str
    points: float
    blocked: bool
    recent_clean: int
    recent_messages: int
    messages: int


class Stats(BaseModel):
    platform: str
    group: str | None = None
    messages: int
    harmful: int
    harmful_rate: float
    decisions: dict[str, int]
    categories: dict[str, int]
    reasons: dict[str, int]
    warnings: int
    restrictions: int
    replayed: int
    restricted_now: int


class GroupRow(BaseModel):
    group: str
    messages: int
    harmful: int


class Groups(BaseModel):
    platform: str
    groups: list[GroupRow]


class Error(BaseModel):
    detail: str | list = Field(description="what was wrong; for 422 one entry per field")
