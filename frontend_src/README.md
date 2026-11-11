# DPM-101 frontend

The existing React 19/TypeScript, Vite, Tailwind CSS and Lucide interface is connected to the FastAPI backend. UI layout and original institutional logo are preserved.

## Run

```sh
npm install
npm run dev
npm run typecheck
npm run build
```

Use Node 22.12+ or `powershell -ExecutionPolicy Bypass -File .\start.ps1` for the workspace's portable runtime. The backend defaults to `http://localhost:8000`. Copy `.env.example` to `.env.local` and set `VITE_API_BASE_URL` for deployment. Backend CORS must allow the frontend origin. No API keys belong here.

See the [root README](../README.md) for Python, PostgreSQL, Gemini, tests and Render deployment.

## Integration

`src/services/chatService.ts` uses native Fetch for sessions, transcript reconciliation, chat and statistics. Backend sessions are created with `POST /api/session`; saved tab history is reconciled with `GET /api/session/{uuid}`. Unknown sessions start a new conversation with a notice when local history existed. Backend failures do not silently switch to mock answers. New chat creates a new backend session. An API error's friendly message is displayed; Retry retains the original chat request ID. Requests time out after 120 seconds, allowing the backend's bounded retries to complete. Local history is tab-scoped in sessionStorage, with in-memory fallback when storage is restricted. Server history contains completed exchanges; reconciliation explains when unsaved local messages are removed.

Statistics poll every four seconds without overlapping poll requests and refresh after successful chat. Failed reads retain last received values and show an unavailable message. Citations and cache badges use backend values directly. The composer accepts up to 2,000 characters to match the default backend limit, supports Enter/Shift+Enter and stays disabled during processing.

For frontend-only exploration, explicitly set `VITE_DEMO_MODE=true`. It uses a separate sessionStorage key, does not call the backend, returns labeled demonstration responses after 800–1200 ms and keeps all statistics at zero. `/test-error` or `VITE_MOCK_FAILURE=true` exercises mock failures. Restart Vite after changing environment variables.

## Logo

The original was located at `../imgaes/logo-animated-new.gif` (there was no `data/` folder). `public/assets/institution-logo.gif` is an unchanged copy displayed with its aspect ratio preserved.

The composer includes approved-FAQ predictive suggestions with a 200 ms debounce, AbortController cancellation, version refresh and keyboard/touch selection. Selecting fills the input; sending remains a separate action. Errors in this optional feature do not disrupt chat. See [the autocomplete documentation](../backend/AUTOCOMPLETE.md).
