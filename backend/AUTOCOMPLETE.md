# Predictive question autocomplete

The existing composer now displays up to five approved FAQ questions while a student types. Selecting a suggestion fills the input and closes the panel; it never submits automatically. The original welcome cards, messages, citations, logo and chat flow remain intact.

## API and data

`GET /api/faq/suggestions?q=final%20exam&limit=5`

```json
{
  "suggestions": [{"faq_id":"uuid","question":"Approved canonical question","topic":"Topic"}],
  "knowledge_version":"current-document-hash"
}
```

`q` defaults to empty and is limited to 200 characters. `limit` is 1–5, default 5. Empty/one-character/whitespace inputs return no suggestions. Invalid query sizes/limits return the existing consistent validation error structure. Only question ID, question and topic are exposed, never answer/evidence/review data.

The service reuses `ChatService.semantic`: the existing active FAQ pointer, validated approved entries, precomputed canonical/paraphrase vectors, one ONNX model and its bounded inference worker. It does not read the JSON export as a second database. Only approved entries matching the current startup knowledge snapshot and valid current sources/review hashes are eligible. Rejected, outdated, revoked or invalid FAQ sets fail closed. A refresh checks approved content even if the active snapshot ID has not changed.

All autocomplete requests are read-only. They never call Gemini, create a submitted question or increment the three student-facing counters. An independently configurable per-IP rate bucket prevents typing from consuming the chat endpoint's normal rate allowance.

## Ranking

- Normalized prefixes match canonical questions and approved paraphrases.
- Lexical matching uses token overlap, partial tokens, simple general word stemming and conservative spelling similarity. It contains no policy-specific keyword/question mappings.
- For at least 12 characters and three tokens with meaningful content, the existing CPU ONNX worker embeds the input and compares against precomputed FAQ vectors.
- Weighted prefix, lexical and semantic scores are combined; variants are grouped only by FAQ ID. Distinct FAQ IDs, including different assessment scopes, are not merged. The result always displays the approved canonical question.

These discovery scores are tunable relevance scores, not probabilities or answer-confidence estimates. Suggestions do not bypass the separate calibrated answer-selection logic. If inference is unavailable or its bounded queue is full, prefix/lexical suggestions still work.

A 256-item process-local LRU/TTL cache defaults to 15 seconds. Cache keys include the active snapshot ID, normalized query and limit. A snapshot replacement clears the question-search representation and suggestion cache. No new model, database table or persistent response cache was introduced.

## Browser behavior

The reusable `QuestionSuggestions.tsx` component/hook waits 200 ms after input changes, aborts obsolete requests and uses a monotonically increasing sequence to reject stale responses even if cancellation races. Old results disappear immediately when their query no longer matches the input. Clearing, submission, blur, Escape or selection closes the panel.

Arrow Down/Up move the highlighted option. Enter with a highlight selects; a subsequent Enter submits normally. Enter without a highlight preserves normal submission, Shift+Enter inserts a newline, and Tab follows the existing focus order. The textarea exposes combobox/listbox relationships and the active option; visible focus/selected states and a screen-reader status are included.

An unchanged, focused, non-dismissed query rechecks suggestions every ten seconds. Each response replaces the entire set and knowledge version, so version changes do not merge old/new options. No frontend suggestion cache persists across queries or sessions. Backend document updates still follow the existing explicit ingestion/deployment/restart workflow; documents are not live-reloaded from disk.

The panel stays directly above the composer and caps its height against the visual viewport. Options wrap and scroll on smaller screens. Chrome's viewport metadata permits content resizing with the virtual keyboard; small-height mobile CSS keeps the composer within the viewport. Viewport/touch tests passed, but a native Android/iOS keyboard was not emulated by headless tests.

Suggestion errors quietly clear the panel and do not disable typing or submission. Demo mode returns no predictive suggestions instead of inventing an approved FAQ dataset.

## Configuration

All values are backend environment settings; defaults work without editing the private `.env`:

| Variable | Default |
| --- | --- |
| `SUGGESTION_PREFIX_WEIGHT` | `0.50` |
| `SUGGESTION_LEXICAL_WEIGHT` | `0.30` |
| `SUGGESTION_SEMANTIC_WEIGHT` | `0.20` |
| `SUGGESTION_LEXICAL_MIN_SCORE` | `0.40` |
| `SUGGESTION_SEMANTIC_MIN_SIMILARITY` | `0.42` |
| `SUGGESTION_SEMANTIC_MIN_CHARS` | `12` |
| `SUGGESTION_SEMANTIC_MIN_TOKENS` | `3` |
| `SUGGESTION_CACHE_ITEMS` | `256` |
| `SUGGESTION_CACHE_TTL_SECONDS` | `15` |
| `SUGGESTION_REQUESTS_PER_MINUTE` | `240` |

## Verification and measurements

The live approved FAQ snapshot contains **23 FAQs**. The benchmark did not modify their records. `artifacts/autocomplete_report.json` records actual measurements against those FAQs, with suggestion caching cleared between service samples:

| Retrieval path | Warm uncached median | Observed maximum |
| --- | --- | --- |
| Prefix | 0.21 ms | 7.81 ms |
| Lexical | 6.33 ms | 8.10 ms |
| Semantic-assisted | 11.29 ms | 13.05 ms |

Warm loopback HTTP prefix requests had a 2.37 ms median and 4.08 ms maximum across 20 samples. The initial database/index/model refresh took about 3.45 seconds. The benchmark process used about **144.4 MiB RSS**, without a second model or PyTorch. This fits below a nominal 512 MiB limit in the measured process; full hosted capacity and peak multi-user behavior are not established by these measurements. Remote network latency, cold service/database starts and periodic source refreshes can add latency. Existing memory/queue guards retain lexical fallback.

The live before/after statistics were identical and Gemini calls were zero. Browser checks used the real suggestions endpoint and intercepted chat submission only for UI verification, so autocomplete QA did not generate new policy answers through Gemini.

Run backend tests with an isolated PostgreSQL `TEST_DATABASE_URL`, then `python -m pytest -q`. Frontend checks are `npm run typecheck` and `npm run build`. Browser results are recorded in `artifacts/autocomplete_browser_checks.json`; captures are `frontend_src/autocomplete-desktop.png` and `frontend_src/autocomplete-mobile.png`.

## Files

| File | Change |
| --- | --- |
| `app/services/faq_suggestion_service.py` | New hybrid question discovery and bounded suggestion cache. |
| `app/services/semantic_faq_service.py` | Shared bounded query encoder and refreshed approval integrity checks. |
| `app/services/chat_service.py` | Owns the suggestion service using its existing semantic instance. |
| `app/main.py` | Suggestions route and separate autocomplete abuse bucket. |
| `app/config.py`, `app/models/schemas.py`, `.env.example` | Tunable ranking, validation and response types. |
| `../frontend_src/src/components/QuestionSuggestions.tsx` | Debounced/cancellable query hook and accessible dropdown. |
| `../frontend_src/src/components/Helpdesk.tsx` | Existing input integration and keyboard/mouse/touch selection. |
| `../frontend_src/src/services/chatService.ts`, `src/types/chat.ts` | Abort-aware suggestion client and frontend contracts. |
| `../frontend_src/src/index.css`, `../frontend_src/index.html` | Compact responsive panel and viewport support. |
| `tests/test_faq_suggestions.py` | Matching, filtering, cache/version, rate, counter and failure tests. |

Restart an older running backend once to expose the new endpoint. The existing Vite dev server reloads the frontend changes automatically. Normal production builds include the feature; no migration, regeneration, new API key or paid embedding API is required.
