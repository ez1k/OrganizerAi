from typing import Any

from pydantic import BaseModel, Field


class ChatMessage(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    message: str = Field(min_length=1)
    history: list[ChatMessage] = Field(default_factory=list)
    draft_event: dict[str, Any] | None = None
    user_id: str = "local-user"


class FeedbackRequest(BaseModel):
    message: str = Field(min_length=1)
    result: dict[str, Any]
    accepted: bool
    user_id: str = "local-user"


class FeedbackCorrectionRequest(BaseModel):
    corrected_result: dict[str, Any]
    user_id: str = "local-user"
