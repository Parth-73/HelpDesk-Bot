# DPM-101 Course Helpdesk

[Deploy the complete app on Render](https://render.com/deploy?repo=https://github.com/Parth-73/HelpDesk-Bot) · [Hosting setup](DEPLOY.md)

A React 19 frontend and Python 3.12/FastAPI backend answer questions using the supplied official course documents. PostgreSQL persists sessions, exchanges, response caches, request idempotency and live counters. Gemini selects evidence; the server only displays verified complete lines copied from authoritative passages. The original interface and institutional logo are preserved.

For the shortest Windows walkthrough, see [QUICKSTART.md](QUICKSTART.md). The backend launcher is `backend/start.ps1`.

## Setup

Install Python 3.12, Node.js 22.12+ and PostgreSQL (or create a Supabase project).

```sh
cd backend
python -m venv .venv
# Windows PowerShell: .\.venv\Scripts\Activate.ps1
# macOS/Linux: source .venv/bin/activate
pip install -r requirements-dev.txt
```

Copy `backend/.env.example` to `backend/.env`. Set `DATABASE_URL`, `GEMINI_API_KEY` and allowed frontend origins. Never put these secrets in frontend environment variables. Relative document paths resolve from the repository root, not the current working directory. Environment loading always uses `backend/.env`.

```sh
# From backend/:
python -m app.init_db
python -m app
```

Initialization creates missing tables and the singleton statistics row without resetting existing counters. It is idempotent for the initial schema; it is not a schema migration framework. Use a dedicated application database/schema and a database user with appropriate permissions. The app does not silently create an in-memory database or return pretend persisted results when PostgreSQL is absent.

```sh
cd frontend_src
npm install
npm run dev
```

The frontend defaults to `http://localhost:8000`. Copy `.env.example` to `.env.local` to configure another origin. `VITE_DEMO_MODE=true` explicitly restores the isolated frontend mock; production uses real endpoints. A workspace-only `start.ps1` can use the previously downloaded portable Node runtime if Node is not on PATH.

## Offline FAQs and semantic retrieval

The backend now supports explicit Gemini FAQ extraction, source validation, human review, local CPU MiniLM/ONNX matching and atomic index activation. Existing RAG remains the fallback. Start with [the FAQ workflow](backend/FAQ_PIPELINE.md). Live extraction requires `--enable-live`; configured credentials alone do not trigger generation. The configured database now contains an active set of 23 source-reviewed, Gemini-generated FAQs; `backend/artifacts/faq_candidates/` contains the live dataset, review decisions and verification report. `backend/artifacts/mock_validation/` remains explicitly test-only data.

## Architecture and document grounding

`backend/app/main.py` owns API validation, CORS, size limits, rate limiting, readiness and safe errors. `database.py` implements async SQLAlchemy/psycopg persistence and transactional counter updates. Services separate ingestion, policy resolution, BM25 retrieval, Gemini, caching and conversation orchestration. Pydantic Settings configures the service.

Read [the document audit](backend/DOCUMENT_AUDIT.md) for source-specific quirks and all twelve sample questions. The existing documents live in `SD_Assessment/SD_Assessment/course_docs/`; they are never edited. Original-byte hashes define the knowledge-base version. Documents load and index once at startup. Restart/redeploy after changing documents so the new snapshot and hash take effect. The same deployment must use one consistent immutable document snapshot.

Numbered headings and complete bullets keep policy values, dates and exceptions together. Unofficial forum comments, including the embedded prompt injection, never enter the index. Explicit document supersession removes grading v1. Topic-level precedence uses applicable dates and comparable versions; ambiguous conflicting policy metadata results in abstention, not an arbitrary choice.

BM25 ranks passages within recognized policy topics. A conservative vocabulary/facet sufficiency check rejects unsupported details before Gemini; this is tailored to this small corpus and validated against the samples. The system prompt treats question and source text as data and forbids external policy knowledge. Gemini returns a structured response with passage IDs and complete evidence quotes. The backend checks IDs, matches quotes to exact whole lines and maps sources to filenames itself. Generated free-form prose is deliberately not displayed. This prevents new wording or numeric claims from entering an answer, but does not prove that every selected quote fully answers every possible question. Conservative abstention and the bounded corpus remain important limitations.

## Memory, caching and concurrency

Recent completed exchanges are stored in PostgreSQL. Only previous student questions (up to four) help resolve contextual references; assistant messages are not policy evidence. Explicit pronouns and underspecified subjects conservatively require context. The resolved query retrieves fresh authoritative evidence. This heuristic is intentionally cautious and can abstain on unfamiliar paraphrases.

Cache keys hash normalized question, relevant student context, knowledge-base hash, prompt version and configured model. Case, whitespace and terminal punctuation normalize; internal punctuation and meaning-changing words are preserved. Clearly independent questions share caches across sessions; dependent questions include context. Bounded paraphrases can now reuse validated responses through the PostgreSQL semantic index; numerical, negated, conditional, historical and scope-changing questions cannot cross-match. See [the semantic audit and measured results](backend/SEMANTIC_OPTIMIZATION.md).

A bounded TTL/LRU process cache sits in front of PostgreSQL. Persisted records include source filenames and original-byte hashes. Changing documents changes keys; persisted idempotency replays from an older knowledge-base version return `REQUEST_OUTDATED` instead of presenting an old policy as current. Submit a new request ID after that response. Expired persistent cache entries are cleaned hourly while the app runs; table growth for history/request records requires an operator retention policy.

Same-key in-flight generation is shared within a process. Cancelled HTTP waiters do not cancel shared generation. Duplicate request IDs share an in-process task; PostgreSQL also persists payload hash, processing/completed/failed state, ownership token and response. Conflicting payloads return 409. Success commits response, both history messages and cache-hit accounting transactionally. Failed submissions can retry the same ID without recounting the accepted question. A 180-second lease permits recovery after a crash; ownership fencing prevents an old worker from committing an already-recovered exchange. Concurrent different questions in one session return `SESSION_BUSY` rather than racing conversation order.

Deploy **one Uvicorn worker** initially. Process-local generation sharing does not deduplicate different request IDs across workers. Database idempotency still prevents duplicate completed exchanges for the same ID, but a crash after an upstream call and before persistence cannot guarantee exactly-once Gemini execution. Counter increments occur immediately before SDK invocation; a process crash in that small window can overcount an attempt. These are explicit distributed-system limits.

## Statistics

- `total_questions`: one atomic increment when a new valid request ID is accepted; no increment for invalid requests, replay, conflict, or retry of a previously accepted ID. Unsupported questions still count.
- `gemini_api_calls`: one atomic increment immediately before each actual outgoing SDK attempt, including retries. SDK-internal retries are disabled. Cache hits and shared waiters do not increment it.
- `cache_hits`: one increment when an accepted question completes from memory, PostgreSQL, or a shared completed generation. Replaying the same request ID does not increment it again.

The frontend polls every four seconds and refreshes after an answer. Statistics failures show an unavailable note while preserving last received values.

## API

| Endpoint | Purpose |
| --- | --- |
| `POST /api/session` | Create a UUID conversation. |
| `GET /api/session/{uuid}` | Reconcile up to 100 transcript messages with the backend. |
| `POST /api/chat` | Submit `{session_id, request_id, question}`. |
| `GET /api/stats` | Return the three persistent counters. |
| `GET /api/health` | Process liveness; never calls Gemini or PostgreSQL. |
| `GET /api/ready` | Check indexed documents, initialized database and configured AI key; no AI quota consumed. |

Example from PowerShell:

```powershell
$session = Invoke-RestMethod -Method Post http://localhost:8000/api/session
$payload = @{session_id=$session.session_id; request_id=[guid]::NewGuid().ToString(); question='What is the minimum passing score?'} | ConvertTo-Json
Invoke-RestMethod -Method Post http://localhost:8000/api/chat -ContentType application/json -Body $payload
Invoke-RestMethod http://localhost:8000/api/stats
```

Success returns `{answer, sources, cached, session_id}`. Unsupported questions return 200 with explicit abstention and empty sources. All application errors use `{error:{code,message,retryable}}`: validation 400, unknown session 404, idempotency/session conflict 409, body limit 413, abuse limit 429, invalid AI output 502, unavailable dependencies 503, AI timeout 504. Provider 429s become friendly 503 AI-busy responses after bounded retries. Retry-After is honored when short; long provider delays return immediately instead of retrying too early. Frontend retries retain the request ID and loading stays active until completion.

## Supabase and Render

Use the Supabase connection string from your project settings. Percent-encode password characters. The async driver URL is `postgresql+psycopg://...`; ordinary `postgresql://` and `postgres://` are normalized. Add `sslmode=require` for encryption, or configure `sslmode=verify-full` and `sslrootcert` for certificate verification. With the transaction pooler (normally port 6543), set `DATABASE_POOLER=true`; SQLAlchemy uses NullPool and psycopg prepared statements are disabled. Direct/session connections can use the bounded SQLAlchemy pool with `DATABASE_POOLER=false`.

Push the repository to your hosting repository and use the root `render.yaml` blueprint. The blueprint creates PostgreSQL and privately wires `DATABASE_URL`; enter `GEMINI_API_KEY` in Render. Same-origin hosting leaves `ALLOWED_ORIGINS` empty. The free database expires after 30 days; see [hosting setup](DEPLOY.md) for durable-database alternatives. No wildcard credentialed CORS is used. The startup command initializes the initial schema, binds to `0.0.0.0:$PORT`, and runs one worker. The readiness check requires configuration, documents and schema but cannot prove that a configured API key is valid without a live Gemini call. The Docker blueprint builds the existing Vite frontend and serves frontend_src/dist from FastAPI at the same origin. Leave VITE_API_BASE_URL unset for this deployment. A separate static frontend can still use VITE_API_BASE_URL pointing to the HTTPS backend origin. No persistent local disk is needed. Free-tier cold starts, database connection limits and Gemini quotas still apply.

## Testing

```sh
cd backend
# Use an isolated PostgreSQL database. Tests create and drop unique test_* schemas.
# PowerShell:
$env:TEST_DATABASE_URL='postgresql+psycopg://user:password@localhost:5432/helpdesk_test'
python -m pytest -q
# Bash: TEST_DATABASE_URL='postgresql+psycopg://...' python -m pytest -q
python -m compileall -q app
cd ../frontend_src
npm run typecheck
npm run build
```

Tests use mocked Gemini only; no real API key or quota is required. PostgreSQL tests skip explicitly when `TEST_DATABASE_URL` is absent. Unit tests cover document integrity/encoding, precedence, all twelve assessment questions, unsupported requests, normalization and source verification. Integration tests cover persistent cache/restart, version invalidation, atomic counters, concurrency, idempotency, worker-crash leases, cancellation and controlled dependency errors. Tests do not use SQLite as a substitute for PostgreSQL.

## Limits and operations

No claim is made that 1,500 users can run simultaneously: load/capacity testing and provider quota planning are still required. The concurrency tests are bounded correctness checks. Gemini concurrency and queue size are limited, retry jitter avoids synchronized retries, and all network operations have finite timeouts. Live Supabase persistence and Gemini extraction have been verified in this workspace. Configure the private environment and verify connectivity again for each deployment.

There is no student authentication. Session UUIDs act as unguessable bearer identifiers; keep them private. Do not store sensitive student information. Size limits, bounded process state, configurable per-IP rate limits, parameterized SQL and safe errors provide basic abuse controls, not a complete public-service security program. Shared-campus NAT addresses may need a higher rate limit. A new session and backend transcript reconciliation prevent old demo/local history from masquerading as persisted history. Browser reloads show completed server exchanges; failed or unpersisted local messages are not authoritative conversation memory.

Implementation references: [Google Gen AI SDK](https://googleapis.github.io/python-genai/), [SQLAlchemy psycopg dialect](https://docs.sqlalchemy.org/en/20/dialects/postgresql.html#module-sqlalchemy.dialects.postgresql.psycopg), [Supabase connection guidance](https://supabase.com/docs/guides/database/connecting-to-postgres), and [Render Blueprint specification](https://render.com/docs/blueprint-spec).

See [the validation record](backend/VALIDATION.md) for completed checks and verification limits. The original document baseline is recorded in `backend/document_manifest.json`.


## Predictive question suggestions

Typing now searches the active approved FAQ index through `GET /api/faq/suggestions`. The composer debounces requests, supports arrow-key/Enter selection and fills the selected question without automatically sending. Autocomplete reuses local ONNX inference, never calls Gemini and leaves question/API/cache counters unchanged. See [autocomplete implementation, files, configuration and measurements](backend/AUTOCOMPLETE.md). Restart an existing backend once to expose the new route.


## Submission audit — 11 November 2026

Repository: https://github.com/Parth-73/HelpDesk-Bot. Public application URL: pending deployment; no hosted URL has been verified.

See [evaluation report](backend/evaluation_report.md), [machine-readable results](backend/evaluation_results.json) and [requirement traceability](backend/requirement_traceability.md). The current audit passes 112 backend tests, T01–T20 with mocked Gemini, and 12 production-bundle browser checks. Bounded load measurements cover 5, 10, 25 and 50 identical concurrent questions; these do not establish 1,500-user capacity. Actual available local AI session exports and provenance are in [ai_sessions](ai_sessions/README.md).

Chat flow: request/session validation → persisted idempotency → context-aware exact cache → guarded semantic response cache → source-derived critical policy decisions → approved local semantic FAQ → current authoritative document retrieval → Gemini quote selection → exact evidence validation → atomic history/counters/cache persistence. New responses expose answer_path. Historical requests return explicitly labeled superseded policy. Numerical eligibility replies derive thresholds from current source text, preserving both conditions. Autocomplete searches local approved FAQ data without Gemini.

Deploy with the root Render blueprint (Docker runtime). The blueprint wires its managed database URL automatically; set GEMINI_API_KEY as a private runtime secret. Same-origin hosting leaves ALLOWED_ORIGINS empty. Keep one worker for process-level generation sharing. The Docker image builds the frontend, installs Python dependencies and prepares the pinned local FAQ model; startup initializes the schema and serves the app on PORT. The readiness endpoint validates configuration/schema/documents, not live API-key validity. Follow [Render Docker deployment documentation](https://render.com/docs/docker). The [production image and PostgreSQL smoke check](https://github.com/Parth-73/HelpDesk-Bot/actions/runs/42978702000) passed on a clean GitHub runner. Public deployment awaits Render account setup and the private Gemini key; see [DEPLOY.md](DEPLOY.md). On an empty database, prepare/extract/review/publish the FAQs following [FAQ_PIPELINE.md](backend/FAQ_PIPELINE.md); the JSON artifact alone is not the active database index.

GEMINI_REQUESTS_PER_MINUTE can optionally enforce the provider budget assigned to your project; leave unset only when budgeting elsewhere. Never put private API/database credentials into frontend variables. Original course documents and logo are preserved. Standalone legacy scripts in the local FAQ extractor folder are not imported by the application and are excluded from this submission.


## Natural-language retrieval update

Short study/preparation questions now retrieve the source-grounded course overview with explicit scope limits. Top-five FAQ discovery, contextual follow-ups and structured abstention diagnostics are covered by 132 regression tests and live local API/browser checks. See [the investigation and evidence](backend/NATURAL_QUERY_RETRIEVAL.md).

## Semantic retrieval and response caching

The [semantic optimization report](backend/SEMANTIC_OPTIMIZATION.md) records a 100-query benchmark, 55 safe/unsafe cache pairs, three local ONNX model comparisons and PostgreSQL/browser regression results. MiniLM remains the deployment model. Approximate reuse requires a bounded equivalent intent, preserved assessment scope, current source hashes, matching knowledge/prompt/model/embedding/FAQ versions, compatible session context and complete verified evidence. Similarity alone never permits a cache hit. `answer_path=semantic_cache` uses the existing cache-hit counter.

For an existing database, run `python -m app.init_db` from `backend/` before restart to add the semantic cache table; the Docker startup already does this. No new environment variable, service or runtime model download is required. The new prompt version invalidates old response keys. Existing exact cache, idempotency, autocomplete and RAG remain available.
