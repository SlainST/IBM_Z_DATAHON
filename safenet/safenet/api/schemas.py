"""Request bodies (docs/API.md). Unknown fields are refused with 422."""
from pydantic import BaseModel, ConfigDict, Field

from .. import config

ID = r"^[^/\x00-\x1f\x7f]+$"   # 1-128 characters, any UTF-8 except / and control characters


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
