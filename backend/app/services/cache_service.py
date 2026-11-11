import asyncio
from collections import OrderedDict
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from ..database import Database
from ..models.database_models import now
from ..models.schemas import GeneratedAnswer
from ..utils.exceptions import ServiceError
from .document_service import Passage
from .retrieval_service import ABSTENTION


@dataclass(frozen=True)
class Answer:
    text: str
    sources: tuple[tuple[str, str], ...]  # (filename, original file hash)
    origin: str = 'gemini'

    @property
    def filenames(self) -> list[str]:
        return sorted({name for name, _ in self.sources})


def validate_answer(generated: GeneratedAnswer, passages: list[Passage]) -> Answer:
    if not generated.supported:
        if generated.source_ids or generated.quotes:
            raise ServiceError('AI_INVALID_OUTPUT', 'The assistant could not verify its answer. Please try again.', 502)
        return Answer(ABSTENTION, (), origin='abstention')
    supplied = {p.id: p for p in passages}
    if not generated.quotes or set(generated.source_ids) != {q.source_id for q in generated.quotes}:
        raise ServiceError('AI_INVALID_SOURCES', 'The assistant could not verify its sources. Please try again.', 502)
    quotes, sources = [], set()
    for quote in generated.quotes:
        passage = supplied.get(quote.source_id)
        # Complete exact lines prevent invented facts or fragments with removed qualifications.
        if not passage or quote.text.strip() not in passage.text.splitlines():
            raise ServiceError('AI_INVALID_SOURCES', 'The assistant could not verify its sources. Please try again.', 502)
        sources.add((passage.metadata.filename, passage.metadata.source_hash))
        if quote.text.strip() not in quotes:
            quotes.append(quote.text.strip())
    return Answer('\n\n'.join(quotes), tuple(sorted(sources)))


class AnswerCache:
    def __init__(self, db: Database, kb, settings):
        self.db, self.kb, self.settings = db, kb, settings
        self.memory: OrderedDict[str, tuple[datetime, Answer]] = OrderedDict()
        self.inflight: dict[str, asyncio.Task] = {}

    async def lookup(self, key: str) -> Answer | None:
        existing = self.memory.get(key)
        if existing:
            expiry, answer = existing
            if expiry > now():
                self.memory.move_to_end(key)
                return replace(answer, origin='exact_cache')
            self.memory.pop(key)
        row = await self.db.cache_get(key, self.kb.version)
        if row:
            current = {d.filename: d.source_hash for d in self.kb.documents}
            if any(current.get(s.get('filename')) != s.get('hash') for s in row.sources):
                return None
            answer = Answer(row.answer, tuple((s['filename'], s['hash']) for s in row.sources), origin='exact_cache')
            self.remember(key, answer, row.expires_at)
            return answer
        return None

    def remember(self, key: str, answer: Answer, expiry: datetime | None = None):
        self.memory[key] = (expiry or now()+timedelta(seconds=self.settings.cache_ttl_seconds), answer)
        self.memory.move_to_end(key)
        while len(self.memory) > self.settings.cache_max_items:
            self.memory.popitem(last=False)

    async def get_or_create(self, key: str, question: str, produce) -> tuple[Answer, bool]:
        answer = await self.lookup(key)
        if answer:
            return answer, True
        # No await occurs between task lookup and registration; one event loop owns this map.
        task = self.inflight.get(key)
        if task:
            shared_answer, _ = await asyncio.shield(task)
            return shared_answer, True
        if len(self.inflight) >= self.settings.max_pending_requests:
            raise ServiceError('AI_BUSY', 'The assistant is temporarily busy. Please try again shortly.')
        async def generate():
            # Another lookup covers a persistent-cache write that raced the initial lookup.
            cached = await self.lookup(key)
            if cached:
                return cached, True
            answer = await produce()
            await self.db.cache_put(key, question, answer.text,
                [{'filename': name, 'hash': hash_} for name, hash_ in answer.sources], self.kb.version)
            self.remember(key, answer)
            return answer, answer.origin=='semantic_cache'
        task = asyncio.create_task(generate())
        self.inflight[key] = task
        def remove(done):
            if self.inflight.get(key) is done:
                self.inflight.pop(key, None)
            if not done.cancelled():
                done.exception()  # Observe failures even if every HTTP caller disconnected.
        task.add_done_callback(remove)
        return await asyncio.shield(task)

    async def close(self):
        tasks = list(self.inflight.values())
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
