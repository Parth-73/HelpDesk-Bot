# Semantic optimization — visible work record

Date: 11 November 2026. Repository baseline: `3cc2eeb`.

This is a task/work record of this actual assistant session, not a complete client-exported transcript. The user's full instruction and the complete conversation should additionally be exported through the client for assessment submission. No hidden reasoning, credentials or invented dialogue is included here.

## User request summary

Diagnose paraphrase abstentions and repeated Gemini calls; build a labeled semantic benchmark; compare MiniLM, BGE-small and E5-small; implement conservative FAQ matching, contextual resolution and persisted semantic response caching; preserve grounding, policy precedence, endpoints, PostgreSQL, frontend, counters and idempotency; run regressions and report actual results without fabricating measurements.

## Work performed in this session

- Inspected normalization, FAQ embeddings/index/calibration, BM25 sufficiency, context, exact cache and Gemini fallback.
- Preserved a baseline worktree at `3cc2eeb` and verified the original suite against isolated local PostgreSQL and actual pinned MiniLM assets.
- Wrote document-grounded labels for 100 queries and 55 cache-equivalence pairs, with calibration and held-out strata.
- Explicitly downloaded pinned ONNX evaluation assets outside the repository and evaluated models in fresh processes. Runtime code never downloads models.
- Added bounded intent/scope checks, calibrated FAQ reranking and acceptance, a versioned PostgreSQL semantic cache, complete-evidence eligibility, conservative context resolution and shared inference.
- Ran before/after routing and real PostgreSQL/ASGI cache benchmarks; only Gemini was mocked. No production credentials or database were used.
- Verified backend regressions, frontend type/build checks and twelve Chromium production-bundle browser checks. Detailed measured results, limitations and reproduction commands are in `backend/SEMANTIC_OPTIMIZATION.md` and `backend/artifacts/semantic_benchmark/`.

The reported zero incorrect semantic reuse applies only to these finite labeled cases, not arbitrary unseen language. Public deployment/live Gemini verification is outside this measured local run.
