"""
JobMatch AI — Python Backend
RAG pipeline: CSV → Pinecone (embeddings) → GPT-4o (ranking & response)

Endpoints:
  POST /webhook   — accepts {chatInput, sessionId}, returns {output: "...markdown..."}
  GET  /health    — health check
  POST /index     — (re)index the CSV dataset into Pinecone
"""

import os
import re
import json
import math
import ast
import logging
from typing import Optional

import pandas as pd
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from dotenv import load_dotenv
from openai import OpenAI
from pinecone import Pinecone, ServerlessSpec

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────
# Config
# ──────────────────────────────────────────────────────────
OPENAI_API_KEY    = os.getenv("OPENAI_API_KEY", "")
PINECONE_API_KEY  = os.getenv("PINECONE_API_KEY", "")
PINECONE_INDEX    = os.getenv("PINECONE_INDEX", "job-listings1")
PINECONE_CLOUD    = os.getenv("PINECONE_CLOUD", "aws")
PINECONE_REGION   = os.getenv("PINECONE_REGION", "us-east-1")
EMBED_MODEL       = "text-embedding-3-small"   # 1536-dim, cheap & fast
CHAT_MODEL        = os.getenv("OPENAI_CHAT_MODEL", "gpt-4o")
TOP_K             = int(os.getenv("TOP_K", "20"))          # candidates from Pinecone
TOP_N_RESULTS     = int(os.getenv("TOP_N_RESULTS", "5"))   # jobs shown to user
CSV_PATH          = os.getenv(
    "CSV_PATH",
    os.path.join(os.path.dirname(__file__), "GENAI_RAG_Dataset - Sheet1.csv")
)

# ──────────────────────────────────────────────────────────
# Clients (lazy-initialized so missing keys don't crash import)
# ──────────────────────────────────────────────────────────
_openai_client = None
_pc = None


def get_openai() -> OpenAI:
    global _openai_client
    if _openai_client is None:
        if not OPENAI_API_KEY:
            raise RuntimeError("OPENAI_API_KEY is not set. Please add it to your .env file.")
        _openai_client = OpenAI(api_key=OPENAI_API_KEY)
    return _openai_client


def get_pinecone() -> Pinecone:
    global _pc
    if _pc is None:
        if not PINECONE_API_KEY:
            raise RuntimeError("PINECONE_API_KEY is not set. Please add it to your .env file.")
        _pc = Pinecone(api_key=PINECONE_API_KEY)
    return _pc


# ──────────────────────────────────────────────────────────
# Data helpers
# ──────────────────────────────────────────────────────────
def _safe_str(val) -> str:
    if val is None or (isinstance(val, float) and math.isnan(val)):
        return ""
    return str(val).strip()


def _parse_salary(raw: str) -> str:
    """Normalise '$59K-$99K' or '50000-80000' into a readable string."""
    raw = _safe_str(raw)
    if not raw:
        return ""
    raw = raw.replace("$", "").replace(",", "")
    m = re.match(r"(\d+\.?\d*)[Kk]?\s*[-–]\s*(\d+\.?\d*)[Kk]?", raw)
    if m:
        lo, hi = m.group(1), m.group(2)
        # If original had K suffix expand
        if "K" in _safe_str(raw).upper():
            lo = f"${int(float(lo) * 1000):,}"
            hi = f"${int(float(hi) * 1000):,}"
        else:
            lo = f"${int(float(lo)):,}"
            hi = f"${int(float(hi)):,}"
        return f"{lo} – {hi}/yr"
    return raw


def _parse_experience(raw: str) -> str:
    raw = _safe_str(raw)
    if not raw:
        return ""
    # "5 to 15 Years" → "5–15 yrs"
    m = re.match(r"(\d+)\s+to\s+(\d+)\s+[Yy]ears?", raw)
    if m:
        return f"{m.group(1)}–{m.group(2)} yrs"
    return raw


def _parse_benefits(raw: str) -> list[str]:
    raw = _safe_str(raw)
    if not raw:
        return []
    # Strip outer braces/quotes from dict-like string
    raw = raw.strip("{}'\"")
    return [b.strip().strip("'\"") for b in raw.split(",") if b.strip()]


def _parse_skills(raw: str) -> list[str]:
    raw = _safe_str(raw)
    if not raw:
        return []
    # Remove parenthetical qualifiers e.g. "(e.g., React, Angular)"
    raw = re.sub(r"\([^)]*\)", "", raw)
    return [s.strip() for s in re.split(r"[,\n]", raw) if s.strip()]


def _parse_company_profile(raw: str) -> dict:
    raw = _safe_str(raw)
    if not raw:
        return {}
    try:
        # JSON-ish string with possible Python-style single quotes
        return json.loads(raw)
    except Exception:
        try:
            return ast.literal_eval(raw)
        except Exception:
            return {}


def clean_row(row: pd.Series) -> dict:
    """Return a normalised job dict from a CSV row."""
    profile = _parse_company_profile(_safe_str(row.get("Company Profile", "")))
    skills  = _parse_skills(_safe_str(row.get("skills", "")))
    benefits = _parse_benefits(_safe_str(row.get("Benefits", "")))

    return {
        "job_id":          _safe_str(row.get("Job Id", "")),
        "title":           _safe_str(row.get("Job Title", "")),
        "role":            _safe_str(row.get("Role", "")),
        "company":         _safe_str(row.get("Company", "")),
        "location":        _safe_str(row.get("location", "")),
        "country":         _safe_str(row.get("Country", "")),
        "work_type":       _safe_str(row.get("Work Type", "")),
        "company_size":    _safe_str(row.get("Company Size", "")),
        "experience":      _parse_experience(_safe_str(row.get("Experience", ""))),
        "qualifications":  _safe_str(row.get("Qualifications", "")),
        "salary":          _parse_salary(_safe_str(row.get("Salary Range", ""))),
        "description":     _safe_str(row.get("Job Description", "")),
        "responsibilities":_safe_str(row.get("Responsibilities", "")),
        "skills":          skills,
        "benefits":        benefits,
        "sector":          profile.get("Sector", ""),
        "industry":        profile.get("Industry", ""),
        "posting_date":    _safe_str(row.get("Job Posting Date", "")),
        "portal":          _safe_str(row.get("Job Portal", "")),
    }


def job_to_text(job: dict) -> str:
    """Produce a dense text representation for embedding."""
    parts = [
        f"Title: {job['title']}",
        f"Role: {job['role']}",
        f"Company: {job['company']}",
        f"Location: {job['location']}, {job['country']}",
        f"Work Type: {job['work_type']}",
        f"Experience: {job['experience']}",
        f"Qualifications: {job['qualifications']}",
        f"Salary: {job['salary']}",
        f"Sector: {job['sector']} | Industry: {job['industry']}",
        f"Skills: {', '.join(job['skills'][:15])}",
        f"Benefits: {', '.join(job['benefits'][:8])}",
        f"Description: {job['description'][:400]}",
        f"Responsibilities: {job['responsibilities'][:300]}",
    ]
    return "\n".join(p for p in parts if not p.endswith(": "))


# ──────────────────────────────────────────────────────────
# Pinecone helpers
# ──────────────────────────────────────────────────────────
def get_or_create_index() -> object:
    client = get_pinecone()
    existing = [idx.name for idx in client.list_indexes()]
    if PINECONE_INDEX not in existing:
        log.info("Creating Pinecone index '%s'...", PINECONE_INDEX)
        client.create_index(
            name=PINECONE_INDEX,
            dimension=1536,
            metric="cosine",
            spec=ServerlessSpec(cloud=PINECONE_CLOUD, region=PINECONE_REGION),
        )
    return client.Index(PINECONE_INDEX)


def embed_texts(texts: list[str]) -> list[list[float]]:
    resp = get_openai().embeddings.create(model=EMBED_MODEL, input=texts)
    return [r.embedding for r in resp.data]


def index_dataset(force: bool = False) -> int:
    """Load CSV and upsert all jobs into Pinecone. Returns number of records indexed."""
    index = get_or_create_index()

    # Check if already populated
    if not force:
        stats = index.describe_index_stats()
        if stats.total_vector_count > 0:
            log.info("Index already has %d vectors; skipping re-index.", stats.total_vector_count)
            return stats.total_vector_count

    log.info("Loading dataset from %s ...", CSV_PATH)
    df = pd.read_csv(CSV_PATH)
    log.info("Loaded %d rows.", len(df))

    jobs = [clean_row(df.iloc[i]) for i in range(len(df))]

    BATCH = 96  # embed up to 96 texts per API call
    total = 0
    for start in range(0, len(jobs), BATCH):
        batch = jobs[start: start + BATCH]
        texts = [job_to_text(j) for j in batch]
        embeddings = embed_texts(texts)

        vectors = []
        for job, emb in zip(batch, embeddings):
            vid = f"job_{job['job_id']}_{start + len(vectors)}"
            # Store key metadata for retrieval (Pinecone metadata values must be scalar/list)
            meta = {
                "title":        job["title"],
                "role":         job["role"],
                "company":      job["company"],
                "location":     job["location"],
                "country":      job["country"],
                "work_type":    job["work_type"],
                "salary":       job["salary"],
                "experience":   job["experience"],
                "qualifications": job["qualifications"],
                "skills":       job["skills"][:20],
                "benefits":     job["benefits"][:10],
                "description":  job["description"][:500],
                "responsibilities": job["responsibilities"][:300],
                "sector":       job["sector"],
                "industry":     job["industry"],
                "company_size": job["company_size"],
            }
            vectors.append({"id": vid, "values": emb, "metadata": meta})

        index.upsert(vectors=vectors)
        total += len(vectors)
        log.info("Upserted %d / %d vectors...", total, len(jobs))

    log.info("Indexing complete. Total vectors: %d", total)
    return total


def search_jobs(query: str, top_k: int = TOP_K) -> list[dict]:
    """Embed query and return top_k matching job metadata dicts."""
    index = get_or_create_index()
    [query_emb] = embed_texts([query])
    results = index.query(vector=query_emb, top_k=top_k, include_metadata=True)
    return [
        {"score": round(m.score, 4), **m.metadata}
        for m in results.matches
    ]


# ──────────────────────────────────────────────────────────
# LLM prompt & response
# ──────────────────────────────────────────────────────────
SYSTEM_PROMPT = """You are JobMatch AI, an expert career advisor and job matching assistant.

Given a user's profile and a list of candidate job postings (with similarity scores), your task is to:
1. Rank the top {top_n} best-fit jobs
2. Explain each match clearly
3. Provide actionable next steps

Output STRICT Markdown using the following structure — do NOT deviate:

# Your Job Match Results

## Summary
- Jobs Analyzed: <total candidate count>
- Top Matches: {top_n}
- Best Match Score: <score>/10

## Top Job Matches

### <Job Title> @ <Company>
- **Match Score: <N>/10 | Location: <loc> | Salary: <salary>**

**Why It Matches:**
- <reason 1>
- <reason 2>
- <reason 3>

**Gaps:**
- <gap or "None identified">

**Experience Alignment:** <one sentence>

**Recommended Next Steps:**
1. <step 1>
2. <step 2>
3. <step 3>

---

(repeat ### block for each of the top {top_n} jobs)

## Recommended Next Steps
1. <global step 1>
2. <global step 2>
3. <global step 3>

Rules:
- Match scores should be 1–10 based on how well the job fits the user's profile
- Be concise and specific — no filler text
- Do NOT use emojis
- Do NOT output JSON, only the Markdown format above
""".strip()


def build_llm_prompt(user_query: str, candidates: list[dict]) -> str:
    candidate_text = ""
    for i, c in enumerate(candidates, 1):
        skills = ", ".join(c.get("skills", [])[:10])
        benefits = ", ".join(c.get("benefits", [])[:5])
        candidate_text += f"""
[Candidate {i}] (vector similarity: {c['score']})
Title: {c.get('title', '')} | Role: {c.get('role', '')}
Company: {c.get('company', '')} ({c.get('sector', '')} / {c.get('industry', '')})
Location: {c.get('location', '')}, {c.get('country', '')} | Work Type: {c.get('work_type', '')}
Salary: {c.get('salary', '')} | Experience: {c.get('experience', '')} | Qualifications: {c.get('qualifications', '')}
Company Size: {c.get('company_size', '')}
Skills: {skills}
Benefits: {benefits}
Description: {c.get('description', '')[:300]}
Responsibilities: {c.get('responsibilities', '')[:200]}
""".strip() + "\n---\n"

    return f"""USER PROFILE & REQUEST:
{user_query}

CANDIDATE JOB POSTINGS ({len(candidates)} retrieved):
{candidate_text}

Please select the top {TOP_N_RESULTS} matches and respond using the required Markdown format."""


def generate_response(user_query: str, candidates: list[dict]) -> str:
    system = SYSTEM_PROMPT.format(top_n=TOP_N_RESULTS)
    user_msg = build_llm_prompt(user_query, candidates)

    log.info("Calling %s with %d candidates...", CHAT_MODEL, len(candidates))
    response = get_openai().chat.completions.create(
        model=CHAT_MODEL,
        messages=[
            {"role": "system", "content": system},
            {"role": "user",   "content": user_msg},
        ],
        temperature=0.3,
        max_tokens=3000,
    )
    return response.choices[0].message.content.strip()


# ──────────────────────────────────────────────────────────
# FastAPI app
# ──────────────────────────────────────────────────────────
app = FastAPI(title="JobMatch AI Backend", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class WebhookRequest(BaseModel):
    chatInput: str
    sessionId: Optional[str] = None


class WebhookResponse(BaseModel):
    output: str


@app.on_event("startup")
async def startup_event():
    """Auto-index on startup if Pinecone index is empty."""
    if not OPENAI_API_KEY:
        log.warning("OPENAI_API_KEY not set — skipping auto-index.")
        return
    if not PINECONE_API_KEY:
        log.warning("PINECONE_API_KEY not set — skipping auto-index.")
        return
    try:
        index_dataset(force=False)
    except Exception as e:
        log.error("Auto-index failed: %s", e)


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/webhook", response_model=WebhookResponse)
async def webhook(req: WebhookRequest):
    if not req.chatInput.strip():
        raise HTTPException(status_code=400, detail="chatInput is required")

    try:
        candidates = search_jobs(req.chatInput, top_k=TOP_K)
        if not candidates:
            return WebhookResponse(output="No matching jobs found in the database. Please try different search terms.")

        output = generate_response(req.chatInput, candidates)
        return WebhookResponse(output=output)

    except Exception as e:
        log.exception("Error processing request")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/index")
async def reindex(force: bool = False):
    """Trigger re-indexing of the CSV dataset."""
    try:
        count = index_dataset(force=force)
        return {"status": "ok", "vectors_indexed": count}
    except Exception as e:
        log.exception("Indexing error")
        raise HTTPException(status_code=500, detail=str(e))
