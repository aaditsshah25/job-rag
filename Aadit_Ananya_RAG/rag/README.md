# JobMatch AI — RAG Assignment

AI-powered job matching using **Python (FastAPI) + Pinecone + OpenAI GPT-4o**.

---

## Quick Start

**Step 1 — Set up environment**

```bash
cd rag/
pip install -r requirements.txt
cp .env.example .env
# Edit .env and add your OPENAI_API_KEY and PINECONE_API_KEY
# Add GOOGLE_CLIENT_ID to enable Google SSO/profile login
```

**Step 2 — Start the backend**

```bash
start.bat
```

The first startup can index the 2,000 job listings into Pinecone if you enable `INDEX_ON_STARTUP=1`.
For Railway and other production deploys, it is safer to leave startup indexing off and trigger `POST /index?force=true` once after deployment.

**Step 3 — Open the app**

`start.bat` opens the app automatically in your default browser at `http://127.0.0.1:5500/index.html`. No build step needed.

---

## How It Works

```
User fills form → chatInput prompt
    ↓
POST http://localhost:8000/webhook
    ↓
[OpenAI text-embedding-3-small] — embed user query
    ↓
[Pinecone] — retrieve top 20 semantically similar jobs
    ↓
[GPT-4o] — rank & explain top 5 matches, generate Markdown
    ↓
Frontend renders structured job cards
```

---

## File Structure

```
rag/
├── backend.py                            ← Python FastAPI backend (RAG pipeline)
├── requirements.txt                      ← Python dependencies
├── .env.example                          ← Environment variable template
├── GENAI_RAG_Dataset - Sheet1.csv        ← 2,000 job listings dataset
├── GenAI - RAG Assignment - Final.json   ← original n8n workflow (reference)
├── README.md
└── frontend/
    ├── index.html
    ├── app.js                            ← calls http://localhost:8000/webhook
    ├── data.js
    ├── style.css
    └── cors-proxy.js                     ← (legacy, no longer needed)
```

---

## API Endpoints

| Method | Path | Description |
|---|---|---|
| `GET` | `/health` | Health check |
| `POST` | `/webhook` | Main job-match endpoint (used by frontend) |
| `POST` | `/index?force=true` | Re-index the CSV dataset into Pinecone |

### Webhook request/response

```json
// Request
{ "chatInput": "I'm looking for...", "sessionId": "session_123" }

// Response
{ "output": "# Your Job Match Results\n## Summary\n..." }
```

---

## Troubleshooting

| Issue | Fix |
|---|---|
| "RuntimeError: OPENAI_API_KEY is not set" | Add keys to `.env` file |
| Empty results | Check Pinecone index — hit `POST /index?force=true` to re-index |
| Port 8000 in use | Run `uvicorn backend:app --port 8001` and update `N8N_WEBHOOK_URL` in `app.js` |
| First request slow | If you enabled `INDEX_ON_STARTUP=1`, wait for the indexing log line; otherwise run `POST /index?force=true` once |
