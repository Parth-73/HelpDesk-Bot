from datetime import datetime, timezone
from uuid import UUID, uuid4
from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, Integer, String, Text, Uuid
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def now() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class Session(Base):
    __tablename__ = 'sessions'
    session_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Message(Base):
    __tablename__ = 'messages'
    message_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    session_id: Mapped[UUID] = mapped_column(ForeignKey('sessions.session_id', ondelete='CASCADE'))
    request_id: Mapped[UUID] = mapped_column(Uuid)
    role: Mapped[str] = mapped_column(String(16))
    content: Mapped[str] = mapped_column(Text)
    sources: Mapped[list] = mapped_column(JSONB, default=list)
    cached: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    __table_args__ = (Index('ix_messages_session_created', 'session_id', 'created_at'),
                      Index('uq_messages_request_role', 'request_id', 'role', unique=True))


class ResponseCache(Base):
    __tablename__ = 'response_cache'
    cache_key: Mapped[str] = mapped_column(String(64), primary_key=True)
    normalized_question: Mapped[str] = mapped_column(Text)
    answer: Mapped[str] = mapped_column(Text)
    sources: Mapped[list] = mapped_column(JSONB)
    knowledge_base_version: Mapped[str] = mapped_column(String(64))
    prompt_version: Mapped[str] = mapped_column(String(64))
    model_name: Mapped[str] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)


class UsageStatistics(Base):
    __tablename__ = 'usage_statistics'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    total_questions: Mapped[int] = mapped_column(BigInteger, default=0)
    gemini_api_calls: Mapped[int] = mapped_column(BigInteger, default=0)
    cache_hits: Mapped[int] = mapped_column(BigInteger, default=0)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class RequestRecord(Base):
    __tablename__ = 'request_records'
    request_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    session_id: Mapped[UUID] = mapped_column(ForeignKey('sessions.session_id'))
    request_hash: Mapped[str] = mapped_column(String(64))
    knowledge_base_version: Mapped[str] = mapped_column(String(64), default='')
    status: Mapped[str] = mapped_column(String(16))
    owner_token: Mapped[UUID] = mapped_column(Uuid)
    response: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
