# JobMatch AI - RAG Assignment

AI-powered job matching using FastAPI, Pinecone, and Gemma models.

Detailed architecture documentation: see `ARCHITECTURE.md`.

## Quick Start

1. Install dependencies and create `.env`:

```bash
pip install -r requirements.txt
cp .env.example .env
```

2. Fill required keys in `.env`:
- `GOOGLE_API_KEY`
- `PINECONE_API_KEY`
- `JOBMATCH_API_KEY` (recommended)
- Optional: `GEMMA_CHAT_MODEL` (defaults to `gemma-3-27b-it`)
- Optional (Admin panel): `ADMIN_EMAILS` (comma-separated allowlist)

Gemma-only mode is enforced. Non-Gemma model names are ignored.

3. Start backend:

```bash
uvicorn backend:app --reload --port 8000
```

4. Open frontend:
- Open `frontend/index.html` in a browser.

## Indexing Behavior

Open `http://localhost:8000/` in your browser. The backend now serves the frontend directly.

---

## How It Works

- On startup, backend attempts indexing if keys are configured.
- If Pinecone index already has vectors, re-index is skipped.
- `INDEX_MODE` controls ingestion strategy:
  - `hybrid` (default): CSV + external sources
  - `live_only`: external sources only
  - `csv_only`: local dataset only
- To force re-index:

```bash
curl -X POST "http://localhost:8000/index?force=true" -H "X-Api-Key: <JOBMATCH_API_KEY>"
```

## API Endpoints

| Method | Path | Description |
|---|---|---|
| `GET` | `/health` | Health check |
| `GET` | `/readiness` | Checks credentials, DB, CSV, and vector index readiness |
| `POST` | `/webhook` | Main job-match endpoint |
| `POST` | `/debug/retrieval` | Returns compact retrieval candidates |
| `POST` | `/debug/rag-trace` | Returns query, candidates, lexical overlap, model info, and prompt preview |
| `POST` | `/index` | (Re)index dataset (`force=true` optional) |
| `GET` | `/sources/status` | Configured sources + per-source counts from latest index run |
| `GET` | `/jobs/stats` | Canonical job DB count, active count, source counts, and vector count |
| `GET` | `/jobs/browse` | Paginated browse/search over canonical jobs |
| `POST` | `/jobs` | Add one job and index it when credentials are configured |
| `POST` | `/jobs/import-csv` | Upload a CSV and import/index jobs |
| `POST` | `/jobs/refresh` | Fetch configured external sources and index new jobs |
| `POST` | `/parse-resume` | Parse PDF resume to structured profile |
| `POST` | `/cover-letter` | Generate tailored cover letter |
| `POST` | `/compose-recruiter-email` | Generate Gmail-ready recruiter email + tailored resume text |
| `POST` | `/bookmark` | Save bookmark |
| `GET` | `/bookmarks/{session_id}` | Get bookmarks |
| `POST` | `/applications` | Create/update application status |
| `GET` | `/applications/{session_id}` | List applications |
| `PATCH` | `/applications/{application_id}` | Update application fields |
| `POST` | `/feedback` | Store user feedback |
| `POST` | `/send-results` | Email results via Resend |
| `POST` | `/auth/google` | Exchange Google credential for JWT |
| `GET` | `/admin/me` | Admin allowlist check (JWT required) |
| `GET` | `/admin/jobs/blocked` | List blocked jobs |
| `POST` | `/admin/jobs/block` | Block a job by `job_key` |
| `DELETE` | `/admin/jobs/block/{job_key}` | Restore a blocked job |
| `POST` | `/admin/jobs/upload` | Upload jobs CSV (dry-run/commit) |

All protected endpoints require `X-Api-Key` when `JOBMATCH_API_KEY` is set.

## External Source Enrichment

To enrich indexing with external job sources:

1. Set `ENABLE_EXTERNAL_SOURCES=true` in `.env`.
2. Add one or more provider keys/tokens in `.env`.
3. Run `POST /index?force=true`.

Recommended India-focused setup:

```env
ENABLE_EXTERNAL_SOURCES=true
INDEX_MODE=live_only
EXTERNAL_SOURCES=adzuna,jooble,greenhouse,lever,remotive
INDIA_ONLY=true
INCLUDE_REMOTE=true
ADZUNA_COUNTRY=in
ADZUNA_WHERE=india
JOOBLE_LOCATION=India
```

Reference setup details: `SOURCES.md`.

## Troubleshooting

| Issue | Fix |
|---|---|
| `GOOGLE_API_KEY is not set` | Add key to `.env` |
| Empty matches | Force re-index with `POST /index?force=true` |
| Frontend cannot reach backend | Check `frontend/config.js` base URL |
| Port 8000 busy | Use another port and update frontend API base URL |
