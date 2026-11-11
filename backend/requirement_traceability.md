# Requirement traceability

Executed 11 November 2026. Test presence is distinguished from external deployment evidence.

| ID | Verification | Result |
| --- | --- | --- |
| R01 Chat/history | test_api.py; production browser session/reload/citation checks | Pass |
| R02 Follow-ups | test_submission_evaluation.py::test_pronouns_history_and_isolation | Pass |
| R03 Loading | Browser composer disable, duplicate Enter, failure/retry | Pass (mock HTTP) |
| R04 Deduplication | Concurrent duplicate IDs, payload conflicts, restart replay, four load levels | Pass |
| R05 Grounding | T01–T20, twelve supplied samples, unsafe FAQ/RAG quote rejection | Pass (mock Gemini) |
| R06 Citations | Document hashes, unknown IDs/fabricated and partial quotes rejected | Pass |
| R07 Latest/history | Explicit supersession and historical label/source tests | Pass |
| R08 Unsupported | Refund/off-topic tests use no Gemini and invent no citations | Pass |
| R09 Cache | Persistent restart, normalization, context, document and snapshot invalidation | Pass |
| R10 Statistics | Atomic counters, idempotency, failures and 5/10/25/50 load invariants | Pass |
| R11 Errors | Mock 429/500/network/timeout/malformed output, Retry-After, DB failure | Pass |
| R12 Hosting | Docker/Render configuration; static frontend route and configured CORS | Local checks pass; image/public deployment pending |
| R13 Integrity | Original four document SHA-256 values match baseline | Pass |
| R14 Submission | Source, README, reports and actual sanitized AI-session exports | Prepared; public application URL pending |

See evaluation_results.json for machine-readable outcomes and evaluation_report.md for methodological limits. FAQ agent review is not independent human review. No live-provider load test or 1,500-user capacity claim is made.
