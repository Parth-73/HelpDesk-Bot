# First public deployment: query regressions

Public app: https://dpm-101-helpdesk.onrender.com/

On 11 November 2026 the public readiness endpoint returned 200 with documents, database and Gemini configuration ready. A cached exam-duration answer returned the correct 90-minute line and its official source. A new government-photo-ID question reached the Gemini path but failed the strict source check with `AI_INVALID_SOURCES`; no unverified policy was displayed.

## Fixes

- The observed spelling error `deadine` (and plural) resolves to `deadline` for retrieval only. Original input remains in history/logging. No fuzzy correction of entities, numbers or negation was added.
- Bare deadline references in compound questions no longer collapse to the syllabus intent. Current capstone deadline and documented course topics are retrieved and returned together with both citations. The response explicitly distinguishes course coverage from a detailed examination syllabus.
- An explicit final-exam deadline request cannot substitute the capstone deadline. Unsupported qualifiers such as a refund still fail closed.
- Fragments such as `what are the` ask which course item or assessment the student means, without a Gemini request or invented answer.
- Gemini now returns bounded evidence-line IDs instead of reproducing long verbatim quotations. The server maps only provided IDs to the original complete source lines, builds source IDs itself, and retains the existing exact-line validator. Unknown or superseded IDs, inconsistent supported flags and added answer prose are rejected. FAQ extraction remains on its separate existing schema.
- Prompt version `extractive-line-selection-v7` and bounded equivalence version `bounded-intents-v2` invalidate obsolete response entries. Calibration was rerun on the original calibration split with the same measured 0.262859 score/margin point; no threshold was lowered.

All 174 backend tests passed with real PostgreSQL and pinned MiniLM, including 17 new query/provider regressions. The deployment image smoke test additionally checks the actual screenshot's compound typo question and incomplete fragment. The production build/runtime check is run separately in GitHub Actions. These tests do not claim that every unseen question or model selection is correct.

After Render redeploys the commit, verify the two exact screenshot questions in a fresh conversation. Old transcript messages remain preserved; they are not rewritten by deployment. Verify one newly phrased supported RAG question for live-provider source selection as well.

The updated production image and screenshot-question smoke checks passed on the clean GitHub runner: https://github.com/Parth-73/HelpDesk-Bot/actions/runs/42982284303. The original 100-query semantic benchmark was rerun under the new equivalence/prompt versions: held-out top-1 remains 97.0%, Recall@3 100%, accepted-match precision 100%, with zero observed false accepts. See `artifacts/live_retrieval_after.json`. Benchmark CLI model paths now resolve relative to the caller's directory, matching the documented commands.

Subsequent public verification passed after the fixed version went Live: the compound typo question returned the current deadline and course topics with both official citations; the incomplete fragment requested clarification; repetition was cached; and a real Gemini-backed government-photo-ID question returned the exact official ID line. See [sanitized recorded responses](artifacts/live_feature_verification.json).
