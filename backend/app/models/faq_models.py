from datetime import datetime
from uuid import UUID, uuid4
from sqlalchemy import ForeignKey, Index, Integer, String, Text, Uuid, DateTime
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from .database_models import Base, now


class FAQSnapshot(Base):
    __tablename__ = 'faq_snapshots'
    snapshot_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    knowledge_version: Mapped[str] = mapped_column(String(64), index=True)
    prompt_version: Mapped[str] = mapped_column(String(64))
    model_name: Mapped[str] = mapped_column(String(128))
    status: Mapped[str] = mapped_column(String(20), default='building')
    report: Mapped[dict] = mapped_column(JSONB, default=dict)
    semantic_index: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class FAQBatch(Base):
    __tablename__ = 'faq_batches'
    batch_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    snapshot_id: Mapped[str] = mapped_column(ForeignKey('faq_snapshots.snapshot_id', ondelete='CASCADE'), index=True)
    source_ids: Mapped[list] = mapped_column(JSONB)
    status: Mapped[str] = mapped_column(String(20), default='pending')
    extraction_calls: Mapped[int] = mapped_column(Integer, default=0)
    result: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class FAQEntry(Base):
    __tablename__ = 'faq_entries'
    faq_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    snapshot_id: Mapped[str] = mapped_column(ForeignKey('faq_snapshots.snapshot_id', ondelete='CASCADE'), index=True)
    question_hash: Mapped[str] = mapped_column(String(64))
    canonical_question: Mapped[str] = mapped_column(Text)
    answer: Mapped[str] = mapped_column(Text)
    paraphrases: Mapped[list] = mapped_column(JSONB)
    source_ids: Mapped[list] = mapped_column(JSONB)
    evidence_quotes: Mapped[list] = mapped_column(JSONB)
    topic: Mapped[str] = mapped_column(String(128))
    question_type: Mapped[str] = mapped_column(String(32))
    requires_context: Mapped[bool]
    knowledge_version: Mapped[str] = mapped_column(String(64))
    prompt_version: Mapped[str] = mapped_column(String(64))
    verification_status: Mapped[str] = mapped_column(String(20))
    validation_notes: Mapped[list] = mapped_column(JSONB)
    content_hash: Mapped[str] = mapped_column(String(64))
    review: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    __table_args__ = (Index('uq_faq_snapshot_question', 'snapshot_id', 'question_hash', unique=True),)


class FAQCatalog(Base):
    __tablename__ = 'faq_catalog'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    active_snapshot_id: Mapped[str | None] = mapped_column(ForeignKey('faq_snapshots.snapshot_id'), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
