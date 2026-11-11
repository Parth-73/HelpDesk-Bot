# Host the complete DPM-101 app

[Deploy the complete app on Render](https://render.com/deploy?repo=https://github.com/Parth-73/HelpDesk-Bot)

This blueprint creates a free Docker web service and a free PostgreSQL database. The database URL is wired automatically through Render's private network. The production image builds and serves the React frontend and FastAPI backend together, including the pinned MiniLM assets. There is one public HTTPS URL and no separate frontend deployment.

1. Open the deployment link and sign in to Render, using GitHub if convenient. Authorize access only as required to deploy this repository.
2. Review the Blueprint resources. Both plans must say **Free** unless you choose a paid plan. Render account verification, including payment verification if requested by Render, must be completed by the account owner.
3. Enter `GEMINI_API_KEY` in the private environment-variable field. Use the key from your assessment email or Google AI Studio. Never paste it into GitHub, frontend variables or chat.
4. Click **Deploy Blueprint**. Render creates the database, builds the production image, initializes all tables, and starts one Uvicorn worker. Wait until the web service reports **Live**.
5. Open the web service's assigned `https://…onrender.com` URL. `/api/health` must return `{"status":"ok"}` and `/api/ready` must return `status: ready` with all three checks true. Readiness verifies key configuration, not whether the key is valid or has quota.
6. In the UI, try the passing requirements, repeat the question, ask a follow-up, and test an unsupported refund question. Check citations, loading state and the live counters. A genuinely new RAG question verifies Gemini credentials/quota; API failures must show a friendly message.

Send the assigned public URL back in chat for external verification. A deployment configuration, local preview or successful CI image build is not a hosted website; do not submit a URL before it opens publicly.

## Free-plan limits

Render's free PostgreSQL **expires 30 days after creation**. This setup is suitable for the assessment/demo. Upgrade the database or migrate to a durable provider before expiry for ongoing use. Free web services also sleep after inactivity, have cold starts and monthly instance-hour limits. Check the current [Render free-plan terms](https://render.com/docs/free) when deploying. No paid resources are selected by this blueprint.

For an existing durable PostgreSQL/Supabase database, keep it rather than provisioning the temporary database: create a Docker web service directly from the repository and privately set `DATABASE_URL` and `GEMINI_API_KEY`. Set `DATABASE_POOLER=true` only for a transaction-pooler connection, such as Supabase port 6543. The default blueprint uses a direct internal Render connection and `DATABASE_POOLER=false`.

## Optional approved FAQ index

A new database has no approved FAQ snapshot. Core chat, RAG, document policy resolution, exact/semantic response caching, persistence and counters work without one. Predictive FAQ suggestions require publishing an approved FAQ snapshot to this production database. The JSON artifacts in Git are not an active database index. Follow [FAQ_PIPELINE.md](backend/FAQ_PIPELINE.md) to extract, review, calibrate and activate it; ingestion is explicit and never silently consumes Gemini quota during startup. Existing approved database data can instead be migrated securely by its owner.

## Deployment verification

The GitHub Actions **Verify deployment image** workflow builds the actual Dockerfile and runs the actual production startup against disposable PostgreSQL. It verifies the production frontend, readiness, persisted sessions, current policy, cache and counters without calling Gemini. Its key is explicitly a nonfunctional CI placeholder. It does not establish live-provider access, a public URL or 1,500-user capacity.

The local cloud-executor Docker attempt on 11 November 2026 reached dependency installation but exhausted its Docker VFS storage while copying a layer. No production resource was created by that attempt. The workflow provides a separate clean-runner image check. Cloud desktop control tools and Render credentials were not available in the executor; account login and production secret entry remain owner actions.
