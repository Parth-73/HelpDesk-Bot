from typing import Literal
from pydantic import BaseModel, ConfigDict, Field

VerificationStatus = Literal['candidate', 'needs_review', 'approved', 'rejected']


class ExtractedFAQ(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    canonical_question: str = Field(min_length=8, max_length=1000)
    answer: str = Field(min_length=1, max_length=6000)
    paraphrases: list[str] = Field(default_factory=list, max_length=12)
    source_ids: list[str] = Field(min_length=1, max_length=8)
    evidence_quotes: list[str] = Field(min_length=1, max_length=12)
    topic: str = Field(min_length=1, max_length=128)
    question_type: Literal['factual','conceptual','conditional','exception','eligibility','deadline','comparison','calculation','misunderstanding']
    requires_context: bool = False


class FAQExtractionResult(BaseModel):
    faqs: list[ExtractedFAQ] = Field(max_length=200)


class ReviewDecision(BaseModel):
    faq_id: str
    content_hash: str
    decision: Literal['approved','rejected']
    reviewer: str = Field(min_length=1, max_length=100)
    rationale: str = Field(min_length=10, max_length=2000)


class ReviewFile(BaseModel):
    snapshot_id: str
    decisions: list[ReviewDecision]
