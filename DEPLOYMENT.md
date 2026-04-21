# Deployment Guide — JobMatch AI

## Architecture

```
GitHub (aaditsshah25/job-rag)
  ├── Push to main → auto-deploys Vercel + Railway
  ├── frontend/      → Vercel (static HTML/JS/CSS, no build step)
  └── backend.py     → Railway (Python FastAPI, via Docker)
```

## Live URLs

| Service | URL |
|---|---|
| Frontend (dashboard) | https://jobmatch-ai-app.vercel.app |
| Backend API | https://job-rag-production.up.railway.app |

---

## Environment Variables Reference

### Backend (Railway)
| Variable | Description | Example |
|---|---|---|
| `OPENAI_API_KEY` | OpenAI API key | `sk-...` |
| `PINECONE_API_KEY` | Pinecone API key | `...` |
| `PINECONE_INDEX` | Pinecone index name | `job-listings1` |
| `PINECONE_CLOUD` | Pinecone cloud | `aws` |
| `PINECONE_REGION` | Pinecone region | `us-east-1` |
| `JOBMATCH_API_KEY` | Shared secret for frontend→backend auth | any random string |
| `JWT_SECRET` | JWT signing secret | any random string |
| `ALLOWED_ORIGINS` | CORS allowed origins (comma-separated) | see below |
| `RESEND_API_KEY` | Resend email API key | `re_...` |
| `FROM_EMAIL` | Sender email address | `noreply@jobmatchai.dev` |
| `DB_PATH` | SQLite DB path | `./data/jobmatch.db` |
| `ADZUNA_APP_ID` | Adzuna API app ID | `763b212a` |
| `ADZUNA_APP_KEY` | Adzuna API key | `...` |
| `GOOGLE_CLIENT_ID` | Google OAuth client ID | `680440081699-...` |

```
ALLOWED_ORIGINS=https://jobmatch-ai-app.vercel.app,http://localhost:8000,http://127.0.0.1:8000
```

### Frontend (Vercel)
| Variable | Description | Example |
|---|---|---|
| `JOBMATCH_API_URL` | Backend public URL (no trailing slash) | `https://job-rag-production.up.railway.app` |
| `GOOGLE_CLIENT_ID` | Google OAuth client ID | `680440081699-...` |

---

## 1. Vercel Setup (frontend)

The Vercel project is already connected. Key settings:
- **Root Directory**: *(empty — repo root)*
- **Output Directory**: `frontend`
- **Framework**: None (static)
- **Build Command**: *(none)*

### Required env vars on Vercel
```
JOBMATCH_API_URL=https://job-rag-production.up.railway.app
GOOGLE_CLIENT_ID=680440081699-mhuuujlrno9k45p34uec2o4lo5ibt30e.apps.googleusercontent.com
```

### Re-deploy via CLI
```bash
npx vercel --prod
```

---

## 2. Backend Hosting — Railway

Backend is live at: https://job-rag-production.up.railway.app

Deployed via **Dockerfile** at repo root. Railway builds and runs the container automatically on push to `main`.

### Manual redeploy (Railway dashboard)
Railway → your project → Deployments → Redeploy

### Railway alternative: Render
1. New Web Service → connect GitHub repo
2. Build command: `pip install -r requirements.txt`
3. Start command: `uvicorn backend:app --host 0.0.0.0 --port $PORT`
4. Add same environment variables as Railway

---

## 3. Local Development

```bash
# Backend
cd "C:\Users\aadit\Documents\FLAME\YEAR 4\SEM 8\Gen AI\Aadit_Ananya_RAG"
cp .env.example .env   # fill in real keys
.venv/Scripts/activate
uvicorn backend:app --reload --port 8000
# Open http://localhost:8000
```

The dashboard is served by FastAPI at `http://localhost:8000` via the `frontend/` static mount.

---

## 4. Rollback

### Frontend (Vercel)
```bash
npx vercel ls
npx vercel promote <deployment-url>
```
Or: Vercel dashboard → Deployments → click any previous deploy → "Promote to Production"

### Backend (Railway)
Railway dashboard → Deployments → click previous deploy → "Rollback"

---

## 5. CI/CD

GitHub Actions (`.github/workflows/ci.yml`) runs on every push and PR to `main`:
- **backend job**: installs Python deps, compiles `backend.py`, checks imports
- **frontend job**: verifies required static files exist (`index.html`, `app.js`, `config.js`)

Vercel auto-deploys frontend on push to `main`.
Railway auto-deploys backend on push to `main` (requires Railway GitHub integration enabled).

---

## 6. Troubleshooting

### Vercel auto-deploy breaks silently
**Symptom**: Pushing to `main` succeeds, Railway redeploys, but Vercel stays on an old version.

**Cause**: `vercel.json` with both `functions` and `builds` keys is invalid in Vercel CLI v50+. Vercel silently rejects the config and skips the deploy.

**Rule**: `vercel.json` must only use `builds` (static), never `functions`. The backend runs on Railway — Vercel serves only static files.

**Fix**: Remove the `functions` block from `vercel.json`. Then force-deploy from CLI:
```bash
# Create .vercel/project.json first if missing:
# {"projectId":"prj_Jmiol50l1CI6SqXa7mIUtSHYWurW","orgId":"team_8AP6k9j6oXApJv1FUhe4Z1r8"}
npx vercel --prod --yes
```

---

### Frontend calls wrong backend (returns 0 results or 500)
**Symptom**: The UI shows "no jobs found" or API errors, but the Railway backend works fine when called directly.

**Cause**: `frontend/config.js` has `DEFAULT_API_BASE_URL = ''` (empty string), so the frontend calls Vercel's own domain — which has no Python backend, no Pinecone keys, nothing.

**Rule**: `DEFAULT_API_BASE_URL` in `config.js` must always be `'https://job-rag-production.up.railway.app'` (no trailing slash).

**Check**: Open browser DevTools → Network → look at which host the `/search` POST goes to. It must be `job-rag-production.up.railway.app`, not `jobmatch-ai-app.vercel.app`.

---

### Pinecone returns 0 results after Railway redeploy
**Symptom**: Railway restarts (new deploy, crash, scale-to-zero), and all searches return 0 jobs.

**Cause**: The in-memory Pinecone index state is cleared on process restart. Railway must run its startup reindex before results appear.

**Fix**: The backend runs `POST /index` automatically at startup. If it did not run (check Railway logs), trigger it manually:
```bash
curl -X POST https://job-rag-production.up.railway.app/index \
  -H "X-API-Key: jobmatch-secret-2024"
```
Wait ~60s for indexing to complete, then retry the search.

---

### Gemma model hangs or times out
**Symptom**: Searches return the fallback response ("AI ranking is temporarily unavailable") with no Gemma output.

**Root cause options**:
1. **Gemma 4 reasoning mode**: `gemma-4-31b-it` and `gemma-4-26b-a4b-it` output a long `<think>...</think>` reasoning block before the actual answer. With 10 candidate jobs in the prompt this takes >120s and times out.
2. **Google API key quota or rate limit**: Check Railway logs for `429` or `quota` errors.
3. **Wrong model name**: If `GEMMA_CHAT_MODEL` is set to an unrecognized string, the API returns a 404.

**Stable model**: Use `gemma-3-27b-it` — it responds in ~30s and does not use reasoning mode.

**Check Railway logs**:
```
Railway → project → Deployments → current deploy → View Logs
```
Look for lines like `Gemini/Gemma generation failed` — the exception type and message are logged there.

**To change model**: Update `GEMMA_CHAT_MODEL` in Railway environment variables, then redeploy.

---

### "AI ranking is temporarily unavailable" shown to user
The app has a fallback: if Gemma fails for any reason, `generate_response()` catches the exception and returns a deterministic job list with a note at the top. This is intentional — the app keeps working even if the LLM is down.

To diagnose which exception triggered the fallback, check Railway logs for:
```
WARNING  Gemini/Gemma generation failed (<ExceptionType>: <message>)
```
