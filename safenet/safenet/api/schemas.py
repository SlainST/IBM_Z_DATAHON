"""Request and answer bodies (docs/API.md). Unknown request fields are refused with 422.

python scripts/write_schemas.py writes schemas/*.schema.json from these classes; tests/test_api.py checks that
the files are up to date and that real answers match them. The answers are documented, not validated, at run time.
"""
import json
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from .. import config

ID = r"^[^/\x00-\x1f\x7f]+$"   # 1-128 characters, any UTF-8 except / and control characters


class CheckRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", json_schema_extra={"examples": [{   # the PDF example, ready in /docs
        "sender_id": "u_4821", "recipient_id": "u_1093", "group_id": "t_77", "message_id": "m_000123",
        "text": "Great match yesterday Mark. But if you show up on Friday I'll f*cking break your legs."}]})

    sender_id: str = Field(min_length=1, max_length=128, pattern=ID)
    text: str = Field(min_length=1, max_length=config.MAX_TEXT_LEN)
    recipient_id: str | None = Field(default=None, min_length=1, max_length=128, pattern=ID)
    group_id: str = Field(default="general", min_length=1, max_length=128, pattern=ID)
    message_id: str | None = Field(default=None, min_length=1, max_length=128, pattern=ID)


class BatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    messages: list[CheckRequest] = Field(min_length=1, max_length=config.MAX_BATCH)


class _Answer(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Offsets(_Answer):
    start: int
    end: int


class HiddenWord(_Answer):
    written: str
    word: str


class Typo(_Answer):
    word: str
    suggestion: str


class SenderStanding(_Answer):
    level: Literal["normal", "warned", "restricted"]
    change: float
    restrictions: int
    restricted_until: str | None = Field(description="ISO 8601, UTC")


class RelationStanding(_Answer):
    blocked: bool
    change: float


class CheckResponse(_Answer):
    key: str
    platform: str
    group: str
    sender: str
    recipient: str | None
    message_id: str | None
    decision: Literal["allow", "censor", "hold", "block"]
    recipient_sees: str | None
    reason: Literal["threat", "hate", "very_harmful", "profanity_ratio", "spam", "quoted_threat", "harmful",
                    "profanity", "sender_restricted", "relation_blocked"] | None
    worst_sentence: str | None
    harm: float
    wordless_harm: float
    category: Literal["insult", "gender", "religion", "race", "sexual", "threat"] | None
    key_words: list[str]
    censored: list[Offsets]
    hidden_profanity: list[HiddenWord]
    possible_typos: list[Typo]
    sender_standing: SenderStanding
    relation: RelationStanding | None
    suggested_action: Literal["warn_sender", "restrict_sender"] | None
    replayed: bool
    latency_ms: float


class BatchResponse(_Answer):
    results: list[CheckResponse]


SCHEMAS = {"check_request": CheckRequest, "check_response": CheckResponse,
           "batch_request": BatchRequest, "batch_response": BatchResponse}
SCHEMAS_DIR = config.ROOT / "schemas"


def schema_text(model: type[BaseModel]) -> str:
    return json.dumps(model.model_json_schema(), indent=2) + "\n"
