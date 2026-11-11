"""Additive table: rerun app.init_db; existing tables need no column migration."""
from datetime import datetime
from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from .database_models import Base


class SemanticCacheEntry(Base):
    __tablename__ = 'semantic_response_cache'
    cache_key: Mapped[str] = mapped_column(ForeignKey('response_cache.cache_key', ondelete='CASCADE'), primary_key=True)
    original_question: Mapped[str] = mapped_column(Text)
    resolved_question: Mapped[str] = mapped_column(Text)
    intent: Mapped[str] = mapped_column(String(64))
    answer: Mapped[str] = mapped_column(Text)
    sources: Mapped[list] = mapped_column(JSONB)
    knowledge_version: Mapped[str] = mapped_column(String(64), index=True)
    prompt_version: Mapped[str] = mapped_column(String(64))
    model_version: Mapped[str] = mapped_column(String(128))
    embedding_version: Mapped[str] = mapped_column(String(64))
    context_metadata: Mapped[dict] = mapped_column(JSONB)
    embedding: Mapped[list] = mapped_column(JSONB)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
