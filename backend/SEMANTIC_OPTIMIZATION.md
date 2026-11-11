# Semantic retrieval and response-cache audit

Executed 11 November 2026. Baseline: commit `3cc2eeb`. Model calls are local CPU ONNX. No live Gemini key was configured, no production database was accessed, and no live-provider latency or quota claim is made.

## Causes found

- Normalization intentionally preserves punctuation/numbers/negation; broadening it would create unsafe exact-cache collisions. Exact keys include relevant user context, model, prompt, knowledge hash and FAQ snapshot. They previously had no semantic response index.
- Existing MiniLM indexing already included canonical questions and approved paraphrases, top-five deduplicated discovery and BM25 passage hints. The main problem was the acceptance gate, not missing vectors: seven coarse qualifier flags conflate incidental words such as “course” with semantic scope, while allowing some related but non-equivalent questions through.
- Contextual FAQ acceptance previously declined nearly all dependent turns. “And how long?” lacked a bounded referent resolver. Recent explicit user topics now resolve common ellipsis, with clarification for unresolved references and a four-user-turn bound for reference chains.
- The vocabulary veto rejected ordinary wording such as handing in work, a program running, and a grace period still applying. Bounded intent expansion and a small generic query vocabulary now reach BM25/evidence checks. Unknown entities and unsupported detail still fail closed.
- An empty FAQ database disabled embedding access. Semantic response caching now works with explicitly prepared local assets even without an active FAQ snapshot. Missing models and memory/queue limits degrade to exact cache and existing retrieval, without downloads during requests.

## Implementation and safety

The original exact TTL/LRU/PostgreSQL cache remains first. Semantic reuse ranks validated response questions but requires a bounded corpus-specific intent and matching assessment/entity scope. Numbers, logical negation (except the fixed quiz phrase “without penalty”), conditions, historical policy, unknown modifiers and ambiguous multi-topic requests are ineligible. Scope-specific assessment weights, quiz/capstone lateness, course/exam duration, and physical calculator/AI tool questions cannot cross-match. This is a deliberately limited intent grammar, not an open-domain entailment model.

FAQ candidates retain canonical/paraphrase indexing, deduplication and top-k discovery. An intent-compatible candidate is ranked before incompatible discovery hints; acceptance additionally checks calibrated similarity and runner-up margin. Unrecognized formulations keep approved exact FAQ matching, then current document retrieval and evidence validation. They do not use the older approximate acceptance gate. Low FAQ confidence never forces abstention by itself. Policy precedence and the exclusion of the unofficial forum injection remain unchanged.

`semantic_response_cache` is an additive PostgreSQL table. Each entry stores its original/resolved question, intent, answer, source names/hashes, knowledge/prompt/generator/embedding versions, vector, contextual dependency hash and expiry. Contextual entries are isolated by session and exact relevant user context. Independent questions can share across sessions. The context metadata also binds the active approved FAQ snapshot so a replaced/revoked index cannot silently reuse its responses.

A hit revalidates the backing exact-cache entry and current source hashes. Conflicting eligible responses cause a miss. Generated responses enter the semantic index only if they contain the complete current evidence lines for their intent; an adjacent valid quotation is insufficient. Reviewed FAQ answers keep their existing approval/entailment validation. Unsupported and clarification responses are never indexed. Hits return `cached=true`, expose `answer_path=semantic_cache`, and increment the existing transactional cache-hit metric once. Idempotent replays remain uncounted.

One process-wide MiniLM session, one bounded inference executor per service and a 256-query vector LRU avoid repeated model initialization/inference. The semantic index is bounded by `CACHE_MAX_ITEMS`, refreshes from PostgreSQL at most every ten seconds, persists across restarts, and expires through the existing cache cleanup cascade. No vector database, embedding API or new heavyweight service is required.

## Labeled benchmark and limits

`benchmarks/semantic_queries.json` contains 100 queries: 39 calibration, 49 held-out and 12 separately reported approved paraphrases. There are 73 FAQ-positive queries overall and 33 in the held-out split. It covers short questions, follow-ups, current/historical policy, conditions, negation, unsupported requests and related non-equivalences. Ground truth is the four unchanged official course files. Cache evaluation contains 55 labeled question pairs, including changed scope, negation and numerical conditions.

Labels were manually authored by this coding assistant against the documents and existing reviewed FAQ artifacts. “Independent paraphrase” means separately written from existing FAQ phrasing, not reviewed by another person. This is a small development benchmark, not an independently collected blind user study. Some strict scope labels reject a broader FAQ even when its text contains the requested value; false accept means an incorrect FAQ selection under these labels, not necessarily a fabricated fact.

`semantic_calibration.json` records the model fingerprint, equivalence version, benchmark hash and operating point. Only calibration-labeled queries and cache pairs fit the threshold/margin; held-out queries are excluded. Hard negatives rejected by the intent gate never become eligible cosine observations. The empirical score therefore has meaning only inside that bounded grammar. Zero observed false reuse is not a guarantee on unseen or adversarial language. Unknown wording falls back conservatively.

## Original versus improved pipeline

Top-1 and Recall@3 measure distinct FAQ candidates, across canonical questions/paraphrases; the improved figures include intent reranking. Raw embedding ranking is also retained per query in the JSON. Accepted-match precision covers served FAQ answers, and false-positive rate uses non-FAQ-labeled queries as its denominator. Unnecessary abstentions count FAQ-positive queries sent to abstention. Gemini counts below are routing opportunities, not live calls.

| Metric | Original, all 100 | Improved, all 100 | Original, held-out 49 | Improved, held-out 49 |
| --- | ---: | ---: | ---: | ---: |
| Top-1 accuracy | 83.6% | 94.5% | 87.9% | 97.0% |
| Recall@3 | 97.3% | 100.0% | 100.0% | 100.0% |
| Accepted FAQ precision | 91.3% | 100.0% | 90.5% | 100.0% |
| Semantic false-positive rate | 11.1% | 0.0% | 12.5% | 0.0% |
| Incorrect FAQ accepts | 4 | 0 | 2 | 0 |
| Unnecessary abstentions | 5 | 0 | 2 | 0 |
| Abstention rate | 14.0% | 7.0% | 12.2% | 4.1% |
| Gemini fallback routes | 29 | 20 | 15 | 11 |
| Gemini fallback rate | 29.0% | 20.0% | 30.6% | 22.4% |

## Local embedding model comparison

Each model ran in a fresh process, sequentially, on the same questions and approved FAQ formulations. This is symmetric question-to-question matching: MiniLM uses mean pooling, BGE uses CLS without the retrieval instruction, and E5 uses `query: ` on both sides with mean pooling. Vectors are normalized. Models are pinned to revisions and hashes in the JSON reports. Existing MiniLM is quantized; the upstream BGE/E5 artifacts tested are FP32, so resource figures compare these deployable artifacts, not architectural limits or a quantized-model ablation. No Torch runtime was installed.

| Model artifact | Held-out top-1 | Held-out Recall@3 | Mean query + ranking ms | P95 ms | Init ms | Peak process RSS MiB |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| MiniLM-L6-v2 (existing, uint8) | 87.9% | 100.0% | 2.60 | 4.20 | 256.1 | 151.2 |
| bge-small-en-v1.5 (FP32) | 84.8% | 93.9% | 8.83 | 12.46 | 826.9 | 321.3 |
| e5-small-v2 (FP32) | 87.9% | 97.0% | 9.54 | 11.68 | 413.7 | 282.8 |

Retain MiniLM: it ties or beats the tested alternatives on held-out ranking and has the best latency/memory profile for the existing small host. Alternative reports retain the original MiniLM acceptance point for diagnostics; their accepted-answer rates are not a calibrated model comparison and were not used for selection. A future model switch must rebuild the FAQ index and refit acceptance calibration.

## Persisted response-cache workload

The same 55 pairs produce 110 real HTTP/ASGI requests against an isolated PostgreSQL database, with an empty approved FAQ table to exercise a fresh deployment. Repeated left-hand questions prime the cache; the right-hand question probes equivalent or unsafe reuse. Only Gemini is mocked with complete current retrieved quotations. These are measured SDK-substitute invocations; they do not prove live Gemini answer quality or latency.

| Metric | Original | Improved |
| --- | ---: | ---: |
| Gemini attempts (mocked) | 37 | 30 |
| All cache hits | 42 | 73 |
| Semantic probe hits | 0 | 31 |
| Semantic probe hit rate | 0.0% | 56.4% |
| Incorrect semantic reuse | 0 | 0 |
| Mean local request ms | 20.03 | 29.61 |
| P95 local request ms | 25.27 | 50.79 |
| Peak process RSS MiB | 127.4 | 207.3 |

Mocked Gemini attempts decreased by 18.9%. The local request benchmark becomes a few milliseconds slower and uses more memory because a fresh deployment now loads ONNX for semantic response reuse; the original empty-FAQ path did not. Reduced external calls are the benefit. These measurements do not predict real end-to-end Gemini latency or establish 1,500-user capacity.

The dedicated warm inference/ranking benchmark measured mean/P95 2.60/4.20 ms before and 3.34/4.68 ms after, with peak RSS 151.2/153.4 MiB. These are single-process samples on this host, not confidence intervals or load tests.

## Validation and rollout

- Baseline: all 132 existing backend tests pass with isolated PostgreSQL and the actual pinned MiniLM.
- Improved: all 157 backend tests pass, including persistence/restart, context/session isolation, knowledge/prompt/generator/embedding/FAQ snapshot invalidation, incomplete evidence, conflicting answers, counters and replay. See `artifacts/semantic_benchmark/pytest.xml`.
- TypeScript and Vite production build pass. Twelve production-bundle browser checks pass in Chromium using mocked HTTP, including a semantic-cache response, loading/deduplication, citations, history, retry and narrow viewports. See `browser.json`.
- The original course document hash checks pass; no source text or institutional logo was changed.

Run `python -m app.init_db` in `backend/` once before restarting an existing deployment. It adds the semantic table and keeps existing data. The prompt version was bumped to invalidate prior response keys. The existing Docker startup already initializes tables; model downloads remain explicit build/operator work. Keep one Uvicorn worker as documented. Missing calibration/model files disable approximate reuse safely; existing exact cache and RAG continue.

Reproduce from the repository root with the installed backend development requirements and an isolated `TEST_DATABASE_URL`:

```sh
# Production model preparation remains unchanged:
cd backend
python -m app.scripts.prepare_faq_model
python benchmarks/calibrate_semantics.py
python benchmarks/evaluate_semantics.py --model-dir model_assets/minilm --output artifacts/semantic_benchmark/after.json
python benchmarks/evaluate_cache_api.py --output artifacts/semantic_benchmark/cache-after.json
python -m pytest -q
```

For baseline comparisons, checkout `3cc2eeb` in a separate worktree, prepare/link the same model assets there, and pass `--root /path/to/baseline/backend` to the current evaluation scripts. `benchmarks/prepare_models.py --model MODEL_ID --directory /path/to/evaluation-models` explicitly prepares only the requested pinned comparison model. It is never imported by production. Compare alternatives with the same baseline `--root` so the model comparison does not mix pipeline changes. Paths and private database credentials should be supplied locally, never committed.
