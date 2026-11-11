# Evaluation report

Executed 11 November 2026, Windows/Python 3.12, isolated PostgreSQL schemas. 112 backend tests passed, no failures/errors/skips. Production TypeScript/Vite build passed; 12 browser checks passed using Brave/Playwright with mocked HTTP responses. No live Gemini quota was used by this audit.

The 20 required questions pass through the actual chat API, retrieval, source validation and database. Gemini is replaced by a source-line selector in this evaluation. This measures deterministic policy correctness and retrieval/validation integration; it does not measure live model answer selection or deployed latency. The existing twelve supplied sample-question retrieval tests also pass. Numerical final-exam follow-ups at 35% and 45%, ambiguous pronoun clarification, session isolation and explicitly labeled historical policy pass.

## Load measurements

Each run creates independent sessions and submits one identical uncached question concurrently. Mock Gemini latency is 200 ms. One ASGI process, local PostgreSQL; session creation is outside timing. RPS is completed chat requests divided by batch wall time. Percentiles are sorted nearest sample positions. RSS is the whole test process after each run, including earlier tests and native model memory; it is not standalone server memory.

| Concurrent requests | RPS | P50 ms | P95 ms | Errors | Cache reuse | Gemini calls | RSS MiB |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 5 | 10.53 | 255.97 | 473.65 | 0 | 80% | 1 | 319.98 |
| 10 | 8.78 | 474.18 | 1135.74 | 0 | 90% | 1 | 320.57 |
| 25 | 25.05 | 486.0 | 882.48 | 0 | 96% | 1 | 321.77 |
| 50 | 46.48 | 713.99 | 857.45 | 0 | 98% | 1 | 323.48 |

All four runs made one generation call, with (N-1)/N call reduction. These bounded deduplication results cannot establish 1,500-user capacity, provider RPM capacity, distributed-worker behavior or public-host performance.

## Coverage and findings

The audit fixed overly strict lexical rejection of valid questions; added source-derived numeric eligibility decisions, assistant-aware assessment references, historical labels, answer_path, configured production CORS and optional provider RPM budgeting. Response prompt version was bumped to invalidate old cache behavior. Existing persistent idempotency, cache-version checks, FAQ validation, atomic counters, bounded queues, cancellation shielding, retry/backoff and malicious-source exclusion remain covered by regression tests. All four original document hashes match the original manifest.

FAQ answers remain independently gated by source hashes, current authority and reviewed content hashes. Semantic FAQ tests verify zero Gemini generation on a valid match, fallback for unsafe matches, missing model handling, memory/queue bounds and index integrity. Review provenance explicitly states AI-agent review. Autocomplete uses no Gemini and changes no chat counters.

## Reproduce

Install backend/requirements-dev.txt and prepare the pinned model as documented in README.md. Set TEST_DATABASE_URL to an isolated PostgreSQL database, then run:

```sh
python -m pytest -c backend/pytest.ini backend/tests -q --junitxml=backend/artifacts/submission_pytest.xml
cd frontend_src
npm ci
npm run build
```

The browser check source is tests/browser/submission-check.mjs; it requires Playwright and Brave, a static server on 127.0.0.1:8788 serving frontend_src/dist, and adjustment of the local browser/import paths for other machines. Raw backend and browser records are in artifacts/submission_pytest.xml, artifacts/submission_browser.json and artifacts/submission_load/.

## Outstanding external verification

Target repository: https://github.com/Parth-73/HelpDesk-Bot. No public application URL is claimed. Render is not connected, so deployment, hosted database connectivity and public smoke tests remain pending. The Docker image itself has not been built locally because Docker is unavailable. The Dockerfile builds the existing frontend and serves it from the same FastAPI service. Historical live Gemini extraction evidence is retained separately; this audit makes no new live API availability claim. Actual sanitized local user/assistant logs are in ai_sessions/ with their scope manifest.
