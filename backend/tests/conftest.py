import os
from uuid import uuid4
import asyncio
import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from asgi_lifespan import LifespanManager
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.engine import make_url
from app.config import Settings
from app.database import Database
from app.main import create_app
from app.models.schemas import GeneratedAnswer, EvidenceQuote
from app.services.document_service import KnowledgeBase


class FakeGemini:
    def __init__(self, settings, counter):
        self.counter = counter
        self.calls = []
        self.failure = None
        self.delay = .05

    async def generate(self, question, context, passages):
        await self.counter()
        self.calls.append((question, context, passages))
        await asyncio.sleep(self.delay)
        if self.failure:
            raise self.failure
        quotes = [EvidenceQuote(source_id=p.id, text=p.text.splitlines()[0]) for p in passages]
        return GeneratedAnswer(answer='This unchecked prose must never be displayed.', supported=True,
            source_ids=[p.id for p in passages], quotes=quotes)

    async def close(self):
        pass


@pytest.fixture
def kb():
    return KnowledgeBase(Settings().course_docs_path)


@pytest_asyncio.fixture
async def db():
    url = os.getenv('TEST_DATABASE_URL')
    if not url:
        pytest.skip('Set TEST_DATABASE_URL to an isolated PostgreSQL test database')
    if url.startswith('postgresql://'):
        url = url.replace('postgresql://', 'postgresql+psycopg://', 1)
    schema = 'test_' + uuid4().hex
    admin = create_async_engine(url, connect_args={'prepare_threshold':None})
    async with admin.begin() as connection:
        await connection.execute(text(f'CREATE SCHEMA {schema}'))
    scoped = make_url(url).update_query_dict({'options': f'-c search_path={schema}'})
    settings = Settings(database_url=scoped.render_as_string(hide_password=False), gemini_api_key='fake-test-key',
        requests_per_minute=10000, gemini_max_retries=0, database_pooler=False)
    database = Database(settings)
    await database.initialize()
    try:
        yield database
    finally:
        await database.close()
        async with admin.begin() as connection:
            await connection.execute(text(f'DROP SCHEMA {schema} CASCADE'))
        await admin.dispose()


@pytest_asyncio.fixture
async def api(db):
    app = create_app(db.settings, database=db, gemini_factory=FakeGemini)
    async with LifespanManager(app):
        async with AsyncClient(transport=ASGITransport(app=app, raise_app_exceptions=False), base_url='http://test') as client:
            yield client, app


async def session(client):
    response = await client.post('/api/session')
    assert response.status_code == 200, response.text
    return response.json()['session_id']


def payload(session_id, question='What is the minimum passing score?'):
    return dict(session_id=str(session_id), request_id=str(uuid4()), question=question)
