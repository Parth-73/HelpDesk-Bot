# Initial assessment gap analysis

Audit date: 11 November 2026 (Asia/Kolkata). Existing React UI/logo, PostgreSQL persistence, Gemini extraction, 23 active reviewed FAQs, ONNX semantic matching, exact cache, idempotency and autocomplete are present. Presence alone is not a pass.

| Requirement | Initial finding | Planned verification |
| --- | --- | --- |
| R01 Chat | Implemented, response provenance missing | Running API + browser journeys |
| R02 Follow-ups | Pronouns/numerical scenarios can be ambiguous; assistant context excluded | Multi-turn final/overall/eligibility tests |
| R03 Loading | Existing browser checks; repeat after integration | Browser success/failure checks |
| R04 Deduplication | Persistent idempotency and shared tasks present | Replay/conflict/concurrent tests |
| R05 Grounding | Conservative lexical gate rejects valid questions | T01–T20 + supplied sample evaluation |
| R06 Citations | Exact evidence validated | Valid/corrupt source tests |
| R07 Current policy | Explicit supersession works; historical requests always abstain | Current/historical regression cases |
| R08 Unsupported | Deterministic abstention present | Refund/off-topic controls |
| R09 Caching | Process + PostgreSQL cache with version keys | Restart/context/invalidation tests |
| R10 Statistics | Atomic counters present | Counter invariants and load tests |
| R11 Failure handling | SDK bounded retry/timeout/schema validation present | Mock 429/500/network/invalid output |
| R12 Hosting | Render blueprint present; production CORS incorrectly fixed to dev origins | Config fix, startup and deployment audit |
| R13 Integrity | Original hash manifest available | Recompute all four hashes |
| R14 Submission | No local Git repo/assessment remote or actual AI session exports found | Repository/export/public URL need external deliverables |

Additional findings: legacy standalone extractors under `FAQ extractor/` are not imported by the app and will remain untouched. No new database column is required for answer_path because idempotency responses already persist JSON; initialization will be checked for idempotence. Runtime Gemini output is intentionally extractive, so explicit numeric decisions need deterministic verified rule handling. Existing test reports are historical records, not evidence of this audit run.
