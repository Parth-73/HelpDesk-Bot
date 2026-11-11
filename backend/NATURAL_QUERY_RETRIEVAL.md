# Short conversational query correction

Verified locally on 11 November 2026. Open http://localhost:5173 with its API on port 8000. The configured allowed frontend origin is localhost:5173, not 127.0.0.1:5173.

## Root cause

The FAQ index already contained canonical course-content questions and approved paraphrases. However, the calibrated answer gate correctly declined the weaker short-query embedding. Scope qualifiers also excluded some formulations from direct answer matching. The old fallback rejected any unknown meaningful token (including “study”) before BM25/topic retrieval, and its overview router did not recognize broad learning/preparation intents. Gemini therefore never received relevant evidence. This was a routing problem, not proof that the documents lacked content.

Conversation handling also inherited context for questions merely lacking a recognized subject. Generated context labels could themselves trigger unrelated retrieval topics. The correction restricts inheritance to actual references/short ellipsis, uses the latest exchange for referents, and strips generated labels before topic scoring.

## Behavior

The existing calibrated FAQ score/margin and qualifier checks are unchanged. A separate top-five distinct-FAQ discovery pass considers every canonical question and approved paraphrase. Weak candidates are passage hints only; they never authorize serving an FAQ answer. A 0.40 discovery floor allows short semantic-only retrieval, independently of the higher calibrated answer threshold. Current-policy resolution and exact evidence checks still apply.

Retrieval combines those hints with BM25 over headings/content, explicit subject/intent routing and recent relevant context. Recognized learning/preparation intents expand to the course overview; no exact question string or course-topic answer is hard-coded. Detailed unsupported subjects and unsupported policy qualifiers still abstain. Explicit topics take precedence over weak unrelated hints.

When an overview passage answers only the course-content portion of a broad preparation request, the response copies that current authoritative passage and explicitly limits its scope: it does not establish a detailed exam syllabus or study plan. Failure questions can similarly return the actual passing conditions without inventing a retake/remediation procedure. Unknown references ask for clarification. A new prompt/cache version prevents prior blanket-abstention cache entries from hiding the correction.

## Structured diagnostics

`qa_route` and `qa_retrieval` log JSON records correlated by request_id. Stages include context, semantic_faq, document_retrieval, policy, Gemini generation/error, evidence validation/rejection/model abstention and final response/cache path. Reasons distinguish no active index, unavailable encoder, qualifier mismatch, below-threshold score, ambiguous margin, unsupported subjects/qualifiers, missing evidence and ambiguous policy. FAQ IDs/scores and passage IDs are logged; raw questions, transcripts and credentials are not added to these diagnostic records.

## Validation

The full PostgreSQL regression suite passed **132 tests** in 48.40 seconds. The final natural-query and dependency-failure subset passed **36 tests** in 9.03 seconds after the last diagnostic additions. All automated provider calls are mocked; one new regression uses the real pinned ONNX model and approved artifact index. Existing cache/idempotency/counter, FAQ, autocomplete, source-integrity, supersession and malicious-comment tests pass.

New regressions cover all ten requested questions plus the reported wording, unsupported subjects/refunds, context reset, missing referents, top-k grouping across paraphrases and real-model fallback candidates. Source text and thresholds were not changed. No frontend API fields were changed.

The previously running backend returned a blanket abstention to “What to study?”. After restart, seven real HTTP requests using configured PostgreSQL and ONNX verified six content/study variants and the refund abstention. Each content answer cited only `01_course_handbook.txt`. Counter delta: seven questions, zero Gemini generation calls. See `artifacts/natural_queries_live.json`. The returned study answer is:

> DPM-101 is an 8-week online course covering user research, product roadmapping, metrics, and AI feature design.
>
> These are the documented course topics; they do not establish a detailed examination syllabus or a study plan.

The actual frontend browser journey also passed with no mocked HTTP responses or runtime errors: the study answer, citation and repeat cache indicator appeared in the UI. See `artifacts/natural_queries_browser.json`. An initial check at 127.0.0.1:5173 failed because that origin is not allowed by the current CORS configuration; the verified browser check uses localhost:5173.

These are live local checks, not public-host or live-Gemini accuracy measurements. The genuine unsupported scenarios remain detailed exam coverage/study plans, retake procedures, refunds and unrelated subjects. Standalone “When is it?”, “How much?” or “Can I skip one?” requires a supported recent referent and otherwise asks for clarification.

## Files

- `app/services/faq_index.py`: top-k distinct FAQ discovery.
- `app/services/semantic_faq_service.py`: separate calibrated answer and discovery results.
- `app/services/retrieval_service.py`: hybrid fallback, learning intent expansion, context filtering and diagnostics.
- `app/services/context_service.py`: recent referents and explicit subject resolution.
- `app/services/partial_answer_service.py`: supported source portions with scope boundaries.
- `app/services/chat_service.py`: routing, clarification and correlated diagnostic events.
- `app/utils/normalization.py`: cache prompt version bump.
- `tests/test_natural_queries.py`: regression coverage.

Run `python -m pytest -c backend/pytest.ini backend/tests -q` with TEST_DATABASE_URL pointing to an isolated PostgreSQL database. Prepare the pinned model as described in FAQ_PIPELINE.md before running model tests. Original course-document hashes remain covered by test_integrity_and_injection_exclusion.
