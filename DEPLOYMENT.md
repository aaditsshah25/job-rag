# Deployment Guide — JobMatch AI

## Architecture

```
GitHub (aaditsshah25/job-rag)
  ├── Push to main → GitHub Actions CI (build check)
  ├── frontend/          → Vercel project "frontend"   (legacy HTML/JS app)
  ├── frontend-react/    → Vercel project "frontend-react" (React landing page)
  └── backend.py         → Railway (Python FastAPI)
```

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
| `ALLOWED_ORIGINS` | CORS allowed origins (comma-separated) | see below |
| `RESEND_API_KEY` | Resend email API key | `re_...` |
| `FROM_EMAIL` | Sender email address | `noreply@jobmatchai.dev` |
| `DB_PATH` | SQLite DB path | `./data/jobmatch.db` |

```
ALLOWED_ORIGINS=https://jobmatch-ai-app.vercel.app,http://localhost:5173,http://127.0.0.1:5173,http://localhost:8000
```

### Frontend — legacy (Vercel project: "frontend")
| Variable | Description | Example |
|---|---|---|
| `JOBMATCH_API_URL` | Backend public URL | `https://job-rag-production.up.railway.app` |
| `JOBMATCH_API_KEY` | Same as backend `JOBMATCH_API_KEY` | same random string |
| `GOOGLE_CLIENT_ID` | Google OAuth client ID | `680440...apps.googleusercontent.com` |

### Frontend React (Vercel project: "frontend-react")
| Variable | Description | Example |
|---|---|---|
| `VITE_API_BASE_URL` | Backend public URL (no trailing slash) | `https://job-rag-production.up.railway.app` |

---

## Deployment Variables (fill in your values)

```
FRONTEND_PUBLIC_URL  = https://jobmatch-ai-app.vercel.app
BACKEND_PUBLIC_URL   = https://job-rag-production.up.railway.app
VITE_API_BASE_URL    = https://job-rag-production.up.railway.app
ALLOWED_ORIGINS      = https://jobmatch-ai-app.vercel.app,http://localhost:5173,http://127.0.0.1:5173,http://localhost:8000
```

---

## 1. GitHub Setup

The repo is already connected at: https://github.com/aaditsshah25/job-rag

### Add GitHub Actions Secrets (for CI)
Go to: **GitHub → Settings → Secrets and variables → Actions → New repository secret**

No secrets are required for CI to run — it uses stub values for the import check.

---

## 2. Vercel Setup — frontend-react (React Landing Page)

### Option A: Via Vercel Dashboard (recommended)
1. Go to https://vercel.com/new
2. Import GitHub repo `aaditsshah25/job-rag`
3. Set **Root Directory** → `frontend-react`
4. Framework: **Vite** (auto-detected)
5. Build command: `npm run build`
6. Output directory: `dist`
7. Add environment variable:
   - `VITE_API_BASE_URL` = `https://job-rag-production.up.railway.app`
8. Deploy

### Option B: Via CLI (PowerShell)
```powershell
cd "frontend-react"
npx vercel --prod
# Follow prompts, select existing team, create new project "frontend-react"
```

### Connect GitHub for auto-deploy
In Vercel project settings → Git → Connect to `aaditsshah25/job-rag`, root dir `frontend-react`

---

## 3. Vercel Setup — frontend (Legacy HTML/JS App)

Already deployed at https://jobmatch-ai-app.vercel.app

To connect GitHub auto-deploy:
1. Go to https://vercel.com/aadits-projects-b151595d/frontend/settings/git
2. Connect Git Repository → GitHub → `aaditsshah25/job-rag`
3. Set Root Directory → `frontend`
4. Ensure these env vars are set:
   - `JOBMATCH_API_URL` = `https://job-rag-production.up.railway.app`
   - `JOBMATCH_API_KEY` = (your shared secret)
   - `GOOGLE_CLIENT_ID` = `680440081699-mhuuujlrno9k45p34uec2o4lo5ibt30e.apps.googleusercontent.com`

---

## 4. Backend Hosting — Railway

Backend is live at: https://job-rag-production.up.railway.app

### Update ALLOWED_ORIGINS on Railway
1. Go to https://railway.app → your project → Variables
2. Set or update:
```
ALLOWED_ORIGINS=https://jobmatch-ai-app.vercel.app,http://localhost:5173,http://127.0.0.1:5173,http://localhost:8000
```
3. Railway redeploys automatically.

### Railway alternative: Render
If migrating to Render:
1. New Web Service → connect GitHub repo
2. Build command: `pip install -r requirements.txt`
3. Start command: `uvicorn backend:app --host 0.0.0.0 --port $PORT`
4. Add same environment variables as Railway

---

## 5. Exact Order of Operations (first-time setup)

1. Push code to GitHub main (already done)
2. Set Railway `ALLOWED_ORIGINS` env var (manual, Railway dashboard)
3. Deploy `frontend-react` to Vercel as new project with root dir `frontend-react`
4. Connect `frontend` Vercel project to GitHub for auto-deploy
5. Verify CI passes on GitHub Actions

---

## 6. Rollback Steps

### Frontend rollback (Vercel)
```powershell
# List recent deployments
npx vercel ls

# Promote a previous deployment to production
npx vercel promote <deployment-url>
```

Or via Vercel dashboard: Deployments → click any previous deploy → "Promote to Production"

### Backend rollback (Railway)
Railway dashboard → Deployments → click previous deploy → "Rollback"

---

## 7. Local Development (PowerShell)

```powershell
# Backend
cd "C:\Users\aadit\Documents\FLAME\YEAR 4\SEM 8\Gen AI\Aadit_Ananya_RAG"
copy .env.example .env   # then fill in real keys
.venv\Scripts\Activate.ps1
uvicorn backend:app --reload --port 8000

# Frontend React (separate terminal)
cd frontend-react
npm install
# Create .env.local with:  VITE_API_BASE_URL=http://localhost:8000
npm run dev
# Open http://localhost:5173

# Legacy frontend
# Just open http://localhost:8000 (served by FastAPI)
```

---

## 8. CI/CD Summary

GitHub Actions (`.github/workflows/ci.yml`) runs on every push and PR to `main`:
- **backend job**: installs Python deps, compiles `backend.py`, checks imports
- **frontend-react job**: `npm ci` + `npm run build` with production env var

Vercel auto-deploys frontend on push to `main` (after GitHub integration is connected).
Railway auto-deploys backend on push to `main` (if Railway GitHub integration is enabled).
