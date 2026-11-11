from uuid import UUID
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    session_id: UUID
    request_id: UUID
    question: str = Field(min_length=1, max_length=10000)

    @field_validator('question')
    @classmethod
    def not_blank(cls, value: str) -> str:
        value = value.strip()
        if not value or any(ord(c) < 32 and c not in '\n\r\t' for c in value):
            raise ValueError('Question must contain readable text')
        return value


class ChatResponse(BaseModel):
    answer_path: Literal["response_cache", "semantic_faq", "gemini_rag", "deterministic", "abstention"] | None = None
    answer: str
    sources: list[str]
    cached: bool = False
    session_id: UUID


class SessionResponse(BaseModel):
    session_id: UUID


class StatsResponse(BaseModel):
    total_questions: int
    gemini_api_calls: int
    cache_hits: int


class EvidenceQuote(BaseModel):
    source_id: str
    text: str = Field(min_length=1, max_length=5000)


class GeneratedAnswer(BaseModel):
    answer: str = Field(max_length=6000)
    source_ids: list[str] = Field(max_length=8)
    supported: bool
    quotes: list[EvidenceQuote] = Field(max_length=8)


class QuestionSuggestion(BaseModel):
    faq_id: UUID
    question: str
    topic: str


class QuestionSuggestionsResponse(BaseModel):
    suggestions: list[QuestionSuggestion]
    knowledge_version: str | None
