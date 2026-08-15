from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class ChatMessage(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    message: str = Field(min_length=1)
    history: list[ChatMessage] = Field(default_factory=list)
    draft_event: dict[str, Any] | None = None
    user_id: str = "local-user"
    session_id: str | None = None


class FeedbackRequest(BaseModel):
    message: str = Field(min_length=1)
    result: dict[str, Any]
    accepted: bool
    user_id: str = "local-user"


class FeedbackCorrectionRequest(BaseModel):
    corrected_result: dict[str, Any]
    user_id: str = "local-user"


class EventReflectionRequest(BaseModel):
    calendar_event_id: str = Field(min_length=1, max_length=255)
    event_title: str = Field(min_length=1, max_length=500)
    event_start: datetime
    event_end: datetime
    rating: int | None = Field(default=None, ge=1, le=5)
    sentiment: Literal["positive", "neutral", "negative", "mixed"] | None = None
    feedback_text: str | None = None
    worth_repeating: bool | None = None
    user_id: str = "local-user"


class ReflectionAnalysisRequest(BaseModel):
    feedback_text: str = Field(min_length=1, max_length=4000)
    user_id: str = "local-user"


class MotivationReminderRequest(BaseModel):
    remind_at: datetime
    user_id: str = "local-user"


class MotivationReminderNaturalRequest(BaseModel):
    when_text: str = Field(min_length=1, max_length=200)
    user_id: str = "local-user"


class MotivationReminderStatusRequest(BaseModel):
    status: Literal["delivered", "completed", "dismissed"]
    user_id: str = "local-user"
