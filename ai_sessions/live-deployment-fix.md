# Live deployment fix — visible work record

11 November 2026. This is a work record of the actual session, not a complete client-exported transcript.

The user supplied the public Render URL and a screenshot showing abstentions for `what is the deadine and syllabus` and `what are the`. The assistant verified public readiness and a cached cited exam-duration answer. A new ID-requirement question returned a source-validation error, which was reported rather than described as a successful answer.

The implementation preserves compound deadline/course-topic evidence, asks for clarification on incomplete fragments, corrects only the observed unambiguous typo and moves runtime Gemini selection to original evidence-line identifiers. Existing source validation remains intact. Query/provider regressions, PostgreSQL tests and production container smoke checks were added/run. Full notes and verification limits are in `backend/LIVE_DEPLOYMENT_FIX.md`.
