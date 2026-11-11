# Make the application usable on this Windows computer

The frontend is already connected to FastAPI. Two private backend settings are still needed: a PostgreSQL connection URL and a Gemini API key. Private `.env` files are local only; configure them on a fresh checkout using `.env.example`.

1. Create/open a Supabase project. In the dashboard choose **Connect → Transaction pooler**, copy the PostgreSQL URI, and replace its password placeholder with your database password. This is the database password, not a Supabase publishable/anon/service-role API key. Add `?sslmode=require` (or `&sslmode=require` if the URI already has a query). Percent-encode special characters in the password component.
2. Create a Gemini API key in [Google AI Studio](https://aistudio.google.com/apikey).
3. Open `backend/.env` and fill the settings below. Use the actual URL copied from Supabase rather than constructing a hostname from this example:

```dotenv
DATABASE_URL=postgresql://postgres.PROJECT_REF:ENCODED_DATABASE_PASSWORD@YOUR_POOLER_HOST:6543/postgres?sslmode=require
DATABASE_POOLER=true
GEMINI_API_KEY=YOUR_GEMINI_API_KEY
GEMINI_MODEL=gemini-2.5-flash-lite
ALLOWED_ORIGINS=http://localhost:5173
```

Leave the other generated settings unchanged. Keep these credentials in this local file or hosting environment; do not paste them into the frontend. Both local environment files are ignored by Git.

4. Open a PowerShell terminal at `C:\Projects\IIMB` and start the backend:

```powershell
powershell -ExecutionPolicy Bypass -File .\backend\start.ps1
```

The launcher checks for missing settings, initializes the PostgreSQL tables without resetting counters, and starts FastAPI. Keep this terminal open. It uses the Python 3.12 environment already installed in this workspace.

5. In a second terminal at `C:\Projects\IIMB`, start the frontend:

```powershell
powershell -ExecutionPolicy Bypass -File .\frontend_src\start.ps1
```

If a frontend server is already running, use that existing terminal/server. If Vite suggests 5174 or another port, stop the extra Vite instance and restart on 5173, or add the actual frontend origin to `ALLOWED_ORIGINS` and restart the backend.

`frontend_src/.env.local` is already prepared with `VITE_API_BASE_URL=http://localhost:8000`. Keep demo mode unset or false. Restart Vite after changing its environment.

6. Open http://localhost:8000/api/ready. Expect status `ready` with all three checks true. Then open http://localhost:5173 and ask **What is the minimum passing score?** Expect the current 60% overall and 40% final-exam requirement, cited to `03_grading_policy_v2.txt`. Readiness confirms configuration and database access; an FAQ/cache hit does not verify live Gemini key or model access.
7. Click **New chat** and ask the identical question. Expect the cache badge. Check http://localhost:8000/api/stats for real counters. Ask **How do I get a refund?** to verify abstention.

If something fails:

| Symptom | Action |
| --- | --- |
| Missing-settings message | Fill `DATABASE_URL` and `GEMINI_API_KEY` in `backend/.env`. |
| Database initialization fails | Check the copied connection URL, real database password, password encoding, pooler selection and SSL query. Make sure the Supabase project is available. |
| Assistant is not configured | Ensure the key is saved in `backend/.env`, then restart the backend. |
| AI unavailable/rate limited | Check key/project access and Gemini quota; retry later if limited. |
| Browser cannot reach backend | Keep both terminals running; verify base URL, backend readiness and CORS origin. |
| Demonstration responses appear | Remove `VITE_DEMO_MODE=true` from frontend configuration and restart Vite. |

For a public submission, use the root Docker/Render blueprint, which builds and serves the frontend and backend together, and set private runtime secrets plus the deployed origin. Follow the root README for full deployment details. Local startup alone does not create a public URL.

Official setup references: [Supabase PostgreSQL connection instructions](https://supabase.com/docs/guides/database/connecting-to-postgres), [Gemini API keys](https://ai.google.dev/gemini-api/docs/api-key).

FAQ generation is an optional offline workflow. The existing chatbot can continue using RAG while you generate and review candidates. See [backend/FAQ_PIPELINE.md](backend/FAQ_PIPELINE.md); starting the web server never consumes quota to regenerate FAQs.
