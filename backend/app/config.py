from pathlib import Path
from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ROOT / 'backend' / '.env', extra='ignore')
    app_env: str = 'development'
    database_url: SecretStr = SecretStr('')
    database_pooler: bool = False
    database_pool_size: int = Field(5, ge=1, le=30)
    gemini_api_key: SecretStr = SecretStr('')
    gemini_model: str = 'gemini-2.5-flash-lite'
    gemini_timeout_seconds: float = Field(20, gt=0, le=60)
    gemini_max_retries: int = Field(2, ge=0, le=3)
    gemini_requests_per_minute: int | None = Field(None, ge=1)
    gemini_concurrency: int = Field(4, ge=1, le=20)
    gemini_queue_timeout_seconds: float = Field(5, gt=0, le=30)
    course_docs_path: Path = ROOT / 'SD_Assessment' / 'SD_Assessment' / 'course_docs'
    allowed_origins: str = 'http://localhost:5173'
    cache_max_items: int = Field(500, ge=1, le=10000)
    cache_ttl_seconds: int = Field(86400, ge=1)
    max_question_length: int = Field(2000, ge=1, le=10000)
    request_max_bytes: int = Field(16384, ge=1024)
    requests_per_minute: int = Field(60, ge=1)
    max_pending_requests: int = Field(256, ge=1)
    request_lease_seconds: int = Field(180, ge=150)
    log_level: str = 'INFO'
    faq_enabled: bool = True
    faq_extraction_timeout_seconds: float = Field(60, ge=1, le=180)
    faq_model_path: Path = ROOT / 'backend' / 'model_assets' / 'minilm'
    faq_embedding_model: str = 'sentence-transformers/all-MiniLM-L6-v2'
    faq_embedding_revision: str = '1110a243fdf4706b3f48f1d95db1a4f5529b4d41'
    faq_embedding_threads: int = Field(1, ge=1, le=4)
    faq_inference_queue: int = Field(16, ge=1, le=128)
    faq_memory_limit_mb: int = Field(450, ge=100)
    faq_refresh_seconds: int = Field(30, ge=1)
    faq_max_entries: int = Field(1000, ge=1, le=10000)
    suggestion_prefix_weight: float = Field(.50, ge=0, le=1)
    suggestion_lexical_weight: float = Field(.30, ge=0, le=1)
    suggestion_semantic_weight: float = Field(.20, ge=0, le=1)
    suggestion_semantic_min_chars: int = Field(12, ge=3)
    suggestion_semantic_min_tokens: int = Field(3, ge=1)
    suggestion_lexical_min_score: float = Field(.4, ge=0, le=1)
    suggestion_semantic_min_similarity: float = Field(.42, ge=0, le=1)
    suggestion_cache_items: int = Field(256, ge=1, le=5000)
    suggestion_cache_ttl_seconds: int = Field(15, ge=1, le=60)
    suggestion_requests_per_minute: int = Field(240, ge=1)


    @field_validator('faq_model_path')
    @classmethod
    def absolute_model_path(cls, value: Path) -> Path:
        return (ROOT / value).resolve() if not value.is_absolute() else value.resolve()

    @field_validator('course_docs_path')
    @classmethod
    def absolute_docs(cls, value: Path) -> Path:
        return (ROOT / value).resolve() if not value.is_absolute() else value.resolve()

    @model_validator(mode='after')
    def lease_covers_bounded_generation(self):
        budget = (self.gemini_max_retries + 1) * self.gemini_timeout_seconds + self.gemini_queue_timeout_seconds + 9 * self.gemini_max_retries + 30
        if self.request_lease_seconds <= budget:
            raise ValueError('REQUEST_LEASE_SECONDS must exceed the bounded Gemini retry/timeout budget plus 30 seconds')
        return self

    @property
    def origins(self) -> list[str]:
        return [origin.strip() for origin in self.allowed_origins.split(',') if origin.strip()]
