# Assessment implementation and verification checklist

**DPM-101 Course Helpdesk — updated 11 November 2026**

**All functional application requirements in Steps 1–4 are implemented.** The checks below identify which behavior was tested automatically and which was also verified on the public deployment. “Passed” refers to the documented test cases, not a guarantee for every possible question or traffic level.

- **Live app:** https://dpm-101-helpdesk.onrender.com/
- **Repository:** https://github.com/Parth-73/HelpDesk-Bot
- **Backend regression suite:** 174 tests passed, zero failures/errors/skips, with isolated real PostgreSQL and pinned MiniLM; provider failure scenarios use mocks. [Executed test report](backend/artifacts/live_query_regressions.xml).
- **Production browser checks:** 12 passed, including loading, duplicate prevention, citations, history and retry, using the built React app and mocked HTTP responses. [Browser report](backend/artifacts/semantic_benchmark/browser.json).
- **Production container/database smoke checks:** [Passed on GitHub Actions](https://github.com/Parth-73/HelpDesk-Bot/actions/runs/42982284303).
- **Selected public checks:** actual readiness, source-cited compound answer, clarification, cache reuse and a Gemini-backed answer passed. [Sanitized live evidence](backend/artifacts/live_feature_verification.json).

## Step 1 — Chat interface and follow-ups

| Required behavior | Implementation and observed status | Verification |
| --- | --- | --- |
| A student opens the page, types a question and gets a clear answer | **Implemented; tested; verified live.** The React chat calls FastAPI and displays document-grounded answers. | Public compound deadline/topics answer and Gemini-backed government-ID answer; `backend/tests/test_api.py::test_health_session_chat_and_stats`; production container smoke check. |
| Follow-up questions work in the same conversation | **Implemented; tested.** PostgreSQL stores session history. Bounded context resolution handles pronouns, elliptical questions and assessment references; ambiguous references ask for clarification. Context is isolated between sessions. | `backend/tests/test_submission_evaluation.py::test_pronouns_history_and_isolation`; `backend/tests/test_natural_queries.py::test_context_followups_and_reset`; reference-chain and context-isolation tests in `backend/tests/test_semantic_response_cache.py`. |
| Loading indicator and prevention of rapid duplicate sends | **Implemented; tested.** The UI displays its waiting state and disables the composer during a request. Request IDs, shared in-flight work and persisted idempotency prevent duplicate processing. | Browser checks confirm the disabled composer and no duplicate Enter submission. `backend/tests/test_api.py::test_concurrent_double_click_and_changed_payload`; restart/replay and counter tests. |

## Step 2 — Accurate answers from course_docs/

| Required behavior | Implementation and observed status | Verification |
| --- | --- | --- |
| Answer strictly from supplied documents and display source filenames | **Implemented; tested; verified live.** Gemini selects existing evidence-line IDs; the server supplies complete original lines and validates sources. Deterministic policies/approved FAQs also retain source grounding. Invalid evidence is rejected. | `backend/tests/test_evidence_selection.py`; `backend/tests/test_cache_safety.py::test_invalid_sources_do_not_enter_any_cache`; public government-ID answer cites `04_exam_rules_and_faq.txt`; deadline/topics answer cites both official files. |
| Prefer the latest official policy when documents conflict | **Implemented; tested.** Explicit supersession and policy metadata select current official evidence. Grading Version 2 supersedes Version 1. Unofficial student comments, including the embedded instruction injection, cannot override exam rules. An explicitly requested old policy is labeled historical/superseded. | `backend/tests/test_documents.py::test_explicit_supersession_and_latest_policy`, metadata/conflict tests, integrity/injection exclusion and historical-label tests. Public deadline answer uses 15 November 2026 from Version 2. |
| Clearly abstain for missing information or off-topic questions | **Implemented; tested.** Unsupported questions state that the information is not mentioned in the official course documents, rather than inventing facts. Incomplete/ambiguous questions request clarification. | Refund/off-topic tests in `backend/tests/test_api.py`, `backend/tests/test_documents.py` and `backend/tests/test_natural_queries.py`; deployed-container abstention check; public incomplete-question clarification. |

## Step 3 — Smart API usage and live counters

| Required behavior | Implementation and observed status | Verification |
| --- | --- | --- |
| Reuse cached answers instead of making unnecessary Gemini calls | **Implemented; tested; verified live.** Exact memory/PostgreSQL caching plus bounded semantic response reuse includes expiry, source hashes, knowledge/prompt/model/embedding versions, FAQ snapshot and relevant context. Different scopes, numerical scenarios, negation and historical policy cannot freely cross-match. | Persistent-cache/restart/concurrency tests; `backend/tests/test_semantic_response_cache.py`; public repeated compound question returned the same answer with `cached=true`. |
| Display Total Questions Asked | **Implemented; tested.** A new accepted request ID increments the persistent total once; replay does not recount it. | API/database/concurrency tests; production container smoke check; browser displays the stats panel. |
| Display Actual Gemini API Calls Made | **Implemented; tested.** The persistent counter increments immediately before each outgoing SDK attempt, including explicit retries; exact/semantic cache hits do not increment it. | Mocked retry/count tests in `backend/tests/test_failures.py`; cache/counter invariants; actual public `gemini_rag` response verified. |
| Display Answers Served from Cache | **Implemented; tested; cache behavior verified live.** Completed exact, semantic and shared-generation hits are counted transactionally; duplicate-ID replay does not increment again. The UI polls the three counters. | `backend/tests/test_semantic_response_cache.py::test_semantic_cache_persistence_counters_and_replay`; API/concurrency tests; public repeat returned `cached=true`. |
| Friendly behavior on Gemini API errors or rate limits | **Implemented; tested with controlled failures.** 429s, timeouts, network/provider failures and invalid evidence produce structured friendly messages with bounded retry behavior, rather than an application crash. | `backend/tests/test_failures.py`; timeout/cancellation tests; browser friendly-error and retry checks. This is not a claim that real provider rate limits were intentionally exhausted. |

## Step 4 — Host online

**Implemented and publicly verified:** https://dpm-101-helpdesk.onrender.com/

Render serves the React frontend and FastAPI backend at one HTTPS origin, backed by PostgreSQL. Readiness and a source-cited real Gemini answer were checked through the public URL. See [deployment instructions](DEPLOY.md) and [first-deployment fixes](backend/LIVE_DEPLOYMENT_FIX.md).

## Load-test evidence and limits

The [Loader.io result](backend/LOADERIO_LOAD_TEST.md) records **1,500 arrivals distributed over one minute**, **1,500 successful responses**, **170 ms average response time**, and **zero HTTP errors, timeouts or network failures** for the configured readiness workload. It also records 1,500 followed redirects.

This verifies the measured readiness/database workload. It does **not** establish 1,500 simultaneous chat users, chat-answer accuracy under that load, or Gemini quota/capacity. Zero observed incorrect semantic reuse applies to the labeled benchmark/test cases, not arbitrary unseen questions. Free Render PostgreSQL expires 30 days after creation; keep hosting available during assessment evaluation.

## Submission materials

The public app, GitHub code, README, implementation checklist and test reports are available. Existing AI session exports are JSON; the added Markdown work records are explicitly not full conversation exports. The owner should include actual client-exported `.md` conversations in `ai_sessions/` to satisfy the assessment's transcript-format requirement. This remaining submission-artifact step is separate from the functional implementation above.
