# Cicero: frontend

React + Vite + TypeScript + Tailwind v4. Talks to the FastAPI backend on Modal.

## Run locally
```bash
cd frontend
npm install
cp .env.example .env      # leave VITE_API_URL empty for demo mode with sample data
npm run dev
```

## Deploy on Vercel (GitHub import)
1. Import the repo in Vercel and set **Root Directory** to `frontend`.
2. Framework preset: Vite (build `npm run build`, output `dist`).
3. Add env var `VITE_API_URL` = your Modal web endpoint.
4. `vercel.json` already rewrites all routes to `index.html`, so deep links work.

## Backend contract
The UI expects these endpoints (all JSON unless noted):

| Method | Path | Purpose |
|---|---|---|
| POST | `/api/chat/stream` | Run the agents; responds with `text/event-stream` |
| POST | `/api/cases/{case_id}/documents` | Multipart upload, field `file`; returns `{ "id": "..." }` |
| POST | `/api/cases/{case_id}/analyze` | Returns the CaseIntel JSON (see `src/types.ts`) |
| GET | `/api/models` | Returns `[{ id, name, note? }]` (optional) |

**Request to `/api/chat/stream`:** see `ChatRequest` in `src/types.ts`
(`prompt`, `model`, `mode`, `jurisdiction`, `agent_models`, `document_ids`, `history`, ...).

**Response:** SSE frames, one JSON event per `data:` line, e.g.
```
data: {"type":"execution","executionId":"exec_1"}

data: {"type":"agent_start","agent":"researcher","text":"Researching authorities"}

data: {"type":"tool","agent":"researcher","tool":"legal_database_search","text":"termination cure period"}

data: {"type":"evidence","evidence":{"id":"E1","kind":"judgment","title":"...","authority":"persuasive","verification":"unverified","passage":"..."}}

data: {"type":"token","text":"The clause requires notice [E1]. "}

data: {"type":"done"}
```
Other event types: `step`, `arguments`, `evaluation`, `error`. Citations in answer text are written
`[E1]`; the UI turns them into numbered chips and shows red if no matching evidence was sent.
Agent ids: `orchestrator`, `analyzer`, `researcher`, `argument`, `counterargument`, `evaluator`.

## FastAPI notes
```python
from fastapi.middleware.cors import CORSMiddleware
app.add_middleware(CORSMiddleware, allow_origins=["https://<your-app>.vercel.app", "http://localhost:5173"],
                   allow_methods=["*"], allow_headers=["*"])
# StreamingResponse(gen(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
```
Never put the Meta API key in this app. Keep it in a Modal secret.

## Structure
```
src/
  App.tsx, main.tsx, index.css, store.ts (state, persisted), types.ts (contracts)
  lib/        api.ts (backend client + SSE), mock.ts (demo data), events.ts (event reducer), ingest.ts, export.ts, util.ts
  components/ Sidebar, Composer, ModelPicker, MessageView, AgentTrace, EvidenceDrawer, Analysis, DeadlineList, ui
  pages/      ChatPage, CasesPage, CaseWorkspace, DeadlinesPage, SettingsPage
```
