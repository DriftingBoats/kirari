from __future__ import annotations

from pydantic import BaseModel, Field


class FileUpdate(BaseModel):
    content: str


class BoardCreate(BaseModel):
    author: str = "user"
    text: str
    source: str = "manual"


class CalendarCreate(BaseModel):
    layer: str
    title: str
    description: str = ""
    starts_at: float
    ends_at: float | None = None
    source: str = "manual"
    confirmed: bool = True


class ReminderCreate(BaseModel):
    title: str
    description: str = ""
    remind_at: float
    repeat_rule: str = ""
    source: str = "manual"


class ReviewAction(BaseModel):
    action: str


class ChatRequest(BaseModel):
    text: str = Field(min_length=1, max_length=12000)
    chat_id: int = 0
