# Validation record

Verified in this workspace on 10 November 2026:

- Python 3.12 backend compilation: passed.
- Pytest: **47 passed**, using a real isolated PostgreSQL 17 database and mocked Gemini calls. No real Gemini quota consumed.
- All twelve supplied sample questions: expected authoritative passages or explicit abstention verified.
- Concurrent correctness test: twelve independent sessions asking the same uncached question received answers from one mocked generation, with twelve accepted-question increments and eleven shared/cache-served increments.
- Duplicate-ID replay, mismatched payload conflicts, failed retry, cancellation, stale processing recovery, fencing, memory bounds/expiry, persistent-cache restart and document-version invalidation: passed.
- Mocked Gemini 429, Retry-After, timeout, 500, network interruption, malformed output and fabricated citations: controlled failures verified.
- Normal `python -m app` startup: passed on Windows; liveness, real PostgreSQL connectivity, readiness without a key, unsupported-question abstention and the friendly missing-key error were checked over HTTP.
- Frontend `npm run typecheck` and `npm run build`: passed.
- Headless Brave checks using the actual React → FastAPI → PostgreSQL route with a mocked Gemini provider: citations, cache badges, four-second stats polling, session transcript reconciliation, original-ID retry, no duplicated student messages and refund abstention passed.
- Responsive checks at 320px, 390px and 768px: no horizontal overflow. No browser runtime errors observed.
- Original course-document SHA-256 values match the baseline in `document_manifest.json`; the original logo is unchanged.

Preview screenshots are local QA captures with test-database counters, not production usage reports. Temporary test provider code lives only in ignored `.tools/`; it is not part of the backend or deployment. No test/mock provider is enabled by the production configuration.

Not verified: a live Gemini response, Supabase credentials/connectivity, an actual Render deployment, or 1,500-user capacity. Configure private credentials in `backend/.env`/hosting environment before live verification. No credentials were supplied, stored or fabricated. The deployment configuration is prepared; nothing was published externally.

FAQ extension verified on 10 November 2026:

- 71 backend tests passed using mocked Gemini calls, real CPU MiniLM ONNX inference and an isolated local PostgreSQL database.
- Coverage includes batch resume/rerun deduplication, invalid evidence/source/authority rejection, logical passing requirements, explicit hash-bound review, failed replacement safety, empirical threshold/margin calibration, semantic and exact FAQ retrieval, historical/negated/numeric qualifiers, context safeguards, FAQ/RAG integration, zero runtime Gemini calls on FAQ hits, source citations, stale index invalidation, dry-run quota protection, bounded inference queues and explicit resource fallback.
- Dry run: four documents, ten current authoritative passages, one excluded unmoderated section, four superseded passages, three planned extraction batches, zero Gemini requests.
- CPU model measurement: about 111.8 MiB observed RSS after inference, 10.46 ms median single-query inference on ten test questions, 3.69-second cold model load, no PyTorch import. The standalone measurement is recorded in `artifacts/faq_resource_report.json`.
- An end-to-end backend-loaded validation process measured about 150.9 MiB RSS with the ONNX semantic index active. This is not a hosted traffic/load test.
- `artifacts/mock_validation/` contains a deliberately labeled synthetic extraction/review dataset, precomputed real embeddings/index, labeled calibration cases and extraction/matching report. Its three extraction attempts were mocked; real Gemini calls were zero. The temporary PostgreSQL schema was removed after artifact generation. These artifacts are not installed in the configured production database.
- Original four document hashes remain unchanged. Backend compilation and the existing frontend production build passed. The frontend source was not redesigned or modified for this extension.

Live FAQ extraction was not enabled. The local key/database configuration was left unchanged, no live Gemini quota was consumed, and no candidate was approved in the configured Supabase database. Run the explicit extraction and review workflow in `FAQ_PIPELINE.md` to produce and activate a real reviewed dataset.



Live FAQ activation verified after explicit user authorization:

- Fixed two real Gemini schema incompatibilities: unsupported additional-properties fields and excessive constrained-decoding state complexity. The outbound schema is simplified while strict Pydantic validation remains local. Offline generation has a separate 60-second timeout.
- Seven offline request attempts recorded, including four provider-rejected schema requests and three successful Gemini extraction batches. 27 candidates persisted in the configured PostgreSQL database; 23 approved after explicit Codex source review and four rejected. Review metadata clearly states AI-agent rather than human review.
- Source-only normalization resolved filename citations through complete exact evidence and removed false numeric warnings for the known DPM-101 identifier. Original answers and raw model outputs were preserved. Two misleading paraphrases were removed, and valid model-generated threshold questions were associated with the complete AND-condition answer before review.
- Nineteen calibration cases produced an empirical operating point with zero false accepts on those cases; six common paraphrases were subsequently confirmed as local FAQ matches. This is not a universal accuracy guarantee.
- Verified the real FastAPI chat contract against the configured database with Gemini generation blocked during verification: correct 60% overall/40% separate-final answer, actual source filename, zero runtime Gemini attempts, and a cache hit on repetition.
- 76 mocked regression tests passed in the isolated local PostgreSQL database. The temporary test database did not receive or modify the live FAQ snapshot.
- The live dataset, active semantic index, explicit review/curation records and API verification result are in `artifacts/faq_candidates/`. The original document hashes remain unchanged. No Render deployment was performed.

Predictive autocomplete verified on 11 November 2026:

- `GET /api/faq/suggestions` uses the existing active approved FAQ snapshot, shared MiniLM ONNX session and bounded encoder worker. No new FAQ tables or model instances were introduced into the running chat service.
- 85 backend tests passed; the final nine autocomplete tests cover required query intents and typo handling, prefixes without inference, approved/current/source-valid filtering, changed snapshot/revocation behavior, deduplication, bounded caching, concurrency, fallback, configurable ranking, isolated rate limiting and unchanged runtime statistics.
- 19 desktop/mobile browser checks passed: debounce, at most five options, click/touch and Enter fill-only selection, second Enter submission, Shift+Enter, Escape, Tab, obsolete request protection, network failures, clearing, version refresh for an unchanged focused input and responsive bounds. No browser runtime errors observed. Browser chat submission was intercepted to avoid new model calls; suggestions came from the real live FAQ database. Native OS keyboard behavior was not directly emulated.
- Live approved FAQ count: 23. Warm uncached service medians: prefix 0.21 ms, lexical 6.33 ms, semantic-assisted 11.29 ms. Warm loopback HTTP prefix median: 2.37 ms. Initial source/index/model refresh: about 3.45 seconds. Observed benchmark process RSS: about 144.4 MiB; this is not a hosted capacity test.
- Live usage counters remained unchanged and autocomplete made zero Gemini calls. Original document hashes remain unchanged. Frontend TypeScript validation and production build passed.
- Reports: `artifacts/autocomplete_report.json`, `artifacts/autocomplete_browser_checks.json`. Documentation and modified-file inventory: `AUTOCOMPLETE.md`.
- The temporary QA server used port 8002; the user's existing backend process on 8000 was left untouched. Restart that older backend once to expose the new route. No public deployment or live FAQ regeneration was performed for autocomplete.

Hosted readiness load test verified on 11 November 2026:

- Loader.io: 1,500 arriving clients over 60 seconds; 1,500 successes, 170 ms average response time, zero HTTP errors/timeouts/network failures, and 1,500 valid redirects.
- Scope: the configured `/api/ready` workload; not simultaneous chat, answer-quality or Gemini-capacity verification. Historical statements above describe their original validation dates.
- [Public evidence, configuration provenance and limits](LOADERIO_LOAD_TEST.md); [JSON results](artifacts/loaderio_1500_readiness.json).
