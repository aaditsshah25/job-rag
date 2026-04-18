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
