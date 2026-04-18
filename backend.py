"""
JobMatch AI — Python Backend v2.0.0
RAG pipeline: CSV → Pinecone (embeddings) → GPT-4o (ranking & response)

Endpoints:
  POST /webhook          — accepts {profile, sessionId} or {chatInput, sessionId}
  GET  /health           — health check
  POST /index            — (re)index the CSV dataset into Pinecone
  POST /parse-resume     — extract structured profile from PDF resume
  POST /cover-letter     — generate a tailored cover letter
  POST /bookmark         — save a bookmarked job
  GET  /bookmarks/{sid}  — retrieve bookmarks for a session
  POST /feedback         — submit job rating/feedback
  POST /send-results     — email results via Resend API
"""

import os
import re
import json
import math
import ast
import asyncio
import logging
import hashlib
import uuid
import io
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from typing import Optional
from urllib.parse import urlencode

import pandas as pd
from fastapi import FastAPI, HTTPException, Depends, UploadFile, File, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse, RedirectResponse
from pydantic import BaseModel, ValidationError
from dotenv import load_dotenv
from openai import OpenAI
from pinecone import Pinecone, ServerlessSpec
from cachetools import TTLCache
import aiosqlite
from source_ingestion import fetch_configured_sources_with_stats, get_source_config

try:
    from slowapi import Limiter, _rate_limit_exceeded_handler
    from slowapi.util import get_remote_address
    from slowapi.errors import RateLimitExceeded
    _SLOWAPI_AVAILABLE = True
except ImportError:
    _SLOWAPI_AVAILABLE = False

try:
    import pdfplumber
    _PDFPLUMBER_AVAILABLE = True
except ImportError:
    _PDFPLUMBER_AVAILABLE = False

try:
    import resend as resend_lib
    _RESEND_AVAILABLE = True
except ImportError:
    _RESEND_AVAILABLE = False

try:
    import jwt as pyjwt
    _PYJWT_AVAILABLE = True
except ImportError:
    _PYJWT_AVAILABLE = False

try:
    from google.oauth2 import id_token as google_id_token
    from google.auth.transport import requests as google_requests
    _GOOGLE_AUTH_AVAILABLE = True
except ImportError:
    _GOOGLE_AUTH_AVAILABLE = False

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

# ─── Config ───────────────────────────────────────────
OPENAI_API_KEY    = os.getenv("OPENAI_API_KEY", "")
PINECONE_API_KEY  = os.getenv("PINECONE_API_KEY", "")
PINECONE_INDEX    = os.getenv("PINECONE_INDEX", "job-listings1")
PINECONE_CLOUD    = os.getenv("PINECONE_CLOUD", "aws")
PINECONE_REGION   = os.getenv("PINECONE_REGION", "us-east-1")
EMBED_MODEL       = "text-embedding-3-small"
CHAT_MODEL        = os.getenv("OPENAI_CHAT_MODEL", "gpt-4o")
TOP_K             = int(os.getenv("TOP_K", "20"))
TOP_N_RESULTS     = int(os.getenv("TOP_N_RESULTS", "5"))
INDEX_MODE        = os.getenv("INDEX_MODE", "hybrid").strip().lower()
CSV_PATH          = os.getenv(
    "CSV_PATH",
    os.path.join(os.path.dirname(__file__), "GENAI_RAG_Dataset - Sheet1.csv")
)
DB_PATH           = os.getenv("DB_PATH", "./data/jobmatch.db")
JOBMATCH_API_KEY  = os.getenv("JOBMATCH_API_KEY", "")
RESEND_API_KEY    = os.getenv("RESEND_API_KEY", "")
FROM_EMAIL        = os.getenv("FROM_EMAIL", "noreply@jobmatchai.dev")
GOOGLE_CLIENT_ID  = os.getenv("GOOGLE_CLIENT_ID", "")
JWT_SECRET        = os.getenv("JWT_SECRET", "")
JWT_ALGORITHM     = "HS256"
JWT_EXPIRE_HOURS  = int(os.getenv("JWT_EXPIRE_HOURS", "72"))

# ─── Lazy singletons ──────────────────────────────────
_openai_client = None
_pc = None
_last_source_stats: dict[str, object] = {
    "last_indexed_at": None,
    "index_mode": None,
    "external_sources_enabled": False,
    "configured_sources": [],
    "source_counts": {},
    "external_total": 0,
}

def get_openai() -> OpenAI:
    global _openai_client
    if _openai_client is None:
        if not OPENAI_API_KEY:
            raise RuntimeError("OPENAI_API_KEY is not set.")
        _openai_client = OpenAI(api_key=OPENAI_API_KEY)
    return _openai_client

def get_pinecone() -> Pinecone:
    global _pc
    if _pc is None:
        if not PINECONE_API_KEY:
            raise RuntimeError("PINECONE_API_KEY is not set.")
        _pc = Pinecone(api_key=PINECONE_API_KEY)
    return _pc

# ─── Search cache (TTL 10 min) ────────────────────────
_search_cache: TTLCache = TTLCache(maxsize=200, ttl=600)

# ─── Session history (in-memory, 60-min TTL) ──────────
_sessions: dict[str, list] = {}
_session_expiry: dict[str, datetime] = {}
SESSION_TTL_MINUTES = 60

def get_session_history(session_id: str) -> list:
    if session_id in _session_expiry and datetime.utcnow() > _session_expiry[session_id]:
        _sessions.pop(session_id, None)
        _session_expiry.pop(session_id, None)
    return _sessions.get(session_id, [])

def save_session_turn(session_id: str, user_msg: str, assistant_msg: str):
    if session_id not in _sessions:
        _sessions[session_id] = []
    _sessions[session_id].append({"role": "user", "content": user_msg})
    _sessions[session_id].append({"role": "assistant", "content": assistant_msg})
    if len(_sessions[session_id]) > 40:
        _sessions[session_id] = _sessions[session_id][-40:]
    _session_expiry[session_id] = datetime.utcnow() + timedelta(minutes=SESSION_TTL_MINUTES)

# ─── Rate limiter ─────────────────────────────────────
if _SLOWAPI_AVAILABLE:
    limiter = Limiter(key_func=get_remote_address)
else:
    # Stub limiter for when slowapi is not installed
    class _StubLimiter:
        def limit(self, *args, **kwargs):
            def decorator(func):
                return func
            return decorator
    limiter = _StubLimiter()

# ─── API Key auth ─────────────────────────────────────
async def verify_api_key(request: Request):
    if not JOBMATCH_API_KEY:
        return  # no auth configured
    key = request.headers.get("X-Api-Key", "")
    if key != JOBMATCH_API_KEY:
        raise HTTPException(status_code=401, detail="Invalid or missing API key")

# ─── Database init ────────────────────────────────────
async def init_db():
    os.makedirs(os.path.dirname(os.path.abspath(DB_PATH)), exist_ok=True)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS bookmarks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                job_title TEXT,
                company TEXT,
                location TEXT,
                salary TEXT,
                match_score REAL,
                job_data TEXT,
                created_at TEXT
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS feedback (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                job_title TEXT,
                company TEXT,
                rating INTEGER,
                comment TEXT,
                created_at TEXT
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS applications (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                job_title TEXT,
                company TEXT,
                status TEXT DEFAULT 'saved',
                notes TEXT,
                applied_at TEXT,
                created_at TEXT
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS alert_subscriptions (
                email TEXT PRIMARY KEY,
                name TEXT,
                profile_json TEXT,
                frequency TEXT DEFAULT 'weekly',
                active INTEGER DEFAULT 1,
                created_at TEXT
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS resume_enhancements (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                overall_score INTEGER,
                suggestions_json TEXT,
                ats_tips_json TEXT,
                score_breakdown_json TEXT,
                created_at TEXT
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS resume_tailoring (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                job_title TEXT,
                company TEXT,
                tailored_score INTEGER,
                analysis_json TEXT,
                created_at TEXT
            )
        """)
        await db.commit()

# ─── Lifespan ─────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    if OPENAI_API_KEY and PINECONE_API_KEY:
        try:
            index_dataset(force=False)
        except Exception as e:
            log.error("Auto-index failed: %s", e)
    yield

# ─── FastAPI App ──────────────────────────────────────
app = FastAPI(title="JobMatch AI Backend", version="2.0.0", lifespan=lifespan)

FRONTEND_DIR = os.path.join(os.path.dirname(__file__), "frontend")
REACT_FRONTEND_DIR = os.path.join(os.path.dirname(__file__), "frontend-react", "dist")

if _SLOWAPI_AVAILABLE:
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

app.add_middleware(
    CORSMiddleware,
    allow_origins=os.getenv("ALLOWED_ORIGINS", "*").split(","),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ─── Global exception handler ─────────────────────────
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    log.exception("Unhandled exception on %s", request.url)
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})

# ─── Pydantic Models ──────────────────────────────────
class UserProfile(BaseModel):
    name: str = ""
    email: str = ""
    desiredRole: str = ""
    experience: int = 0
    skills: list[str] = []
    education: str = ""
    industry: str = ""
    location: str = ""
    workType: str = "Any"
    salaryMin: Optional[int] = None
    companySize: str = "Any"
    benefits: list[str] = []
    workAuth: str = "Not Specified"
    additional: str = ""

class WebhookRequest(BaseModel):
    chatInput: Optional[str] = None
    profile: Optional[UserProfile] = None
    sessionId: Optional[str] = None

class WebhookResponse(BaseModel):
    output: str

class BookmarkRequest(BaseModel):
    session_id: str
    job_title: str
    company: str
    location: str = ""
    salary: str = ""
    match_score: float = 0.0
    job_data: dict = {}

class FeedbackRequest(BaseModel):
    session_id: str
    job_title: str
    company: str
    rating: int  # 1-5
    comment: str = ""

class CoverLetterRequest(BaseModel):
    profile: UserProfile
    jobTitle: str
    company: str
    jobDescription: str = ""
    tone: str = "professional"

class SendResultsRequest(BaseModel):
    email: str
    name: str
    results_markdown: str

class GoogleAuthRequest(BaseModel):
    credential: str

class DebugRetrievalRequest(BaseModel):
    profile: Optional[UserProfile] = None
    chatInput: Optional[str] = None
    topK: int = 12

class ApplicationCreateRequest(BaseModel):
    session_id: str
    job_title: str
    company: str
    status: str = "saved"
    notes: str = ""

class ApplicationUpdateRequest(BaseModel):
    status: Optional[str] = None
    notes: Optional[str] = None

class TailorResumeRequest(BaseModel):
    resume_text: str
    job_title: str
    company: str
    job_description: str = ""
    job_skills: list[str] = []
    session_id: str = ""

class KeywordGapRequest(BaseModel):
    resume_text: str
    job_description: str
    job_skills: list[str] = []

class RecruiterEmailComposeRequest(BaseModel):
    profile: UserProfile
    recruiter_email: str = ""
    job_title: str
    company: str
    job_description: str = ""
    job_location: str = ""
    match_score: Optional[int] = None
    job_skills: list[str] = []
    resume_text: str
    session_id: str = ""

# ─── Profile query builder ────────────────────────────
def build_query_from_profile(profile: UserProfile) -> str:
    parts = ["I'm looking for job recommendations. Here is my profile:"]
    if profile.name:
        parts.append(f"Name: {profile.name}")
    if profile.desiredRole:
        parts.append(f"Desired Role: {profile.desiredRole}")
    if profile.experience:
        parts.append(f"Years of Experience: {profile.experience}")
    if profile.skills:
        parts.append(f"Key Skills: {', '.join(profile.skills)}")
    if profile.education:
        parts.append(f"Education: {profile.education}")
    if profile.industry:
        parts.append(f"Preferred Industry: {profile.industry}")
    if profile.location:
        parts.append(f"Preferred Location: {profile.location}")
    if profile.workType and profile.workType != "Any":
        parts.append(f"Work Type Preference: {profile.workType}")
    if profile.salaryMin:
        parts.append(f"Minimum Salary: ${profile.salaryMin:,} per year")
    if profile.companySize and profile.companySize != "Any":
        parts.append(f"Company Size Preference: {profile.companySize}")
    if profile.benefits:
        parts.append(f"Benefits Priorities: {', '.join(profile.benefits)}")
    if profile.workAuth and profile.workAuth != "Not Specified":
        parts.append(f"Work Authorization Status: {profile.workAuth}")
    if profile.additional:
        parts.append(f"Additional Preferences:\n{profile.additional}")
    parts.append("Please find the best matching jobs for my profile from the available postings.")
    return "\n".join(parts)

# ─── Data cleaning utilities ──────────────────────────
def _safe_str(val) -> str:
    if val is None or (isinstance(val, float) and math.isnan(val)):
        return ""
    return str(val).strip()

def _parse_salary(raw: str) -> str:
    raw = _safe_str(raw)
    if not raw:
        return ""
    raw = raw.replace("$", "").replace(",", "")
    m = re.match(r"(\d+\.?\d*)[Kk]?\s*[-\u2013]\s*(\d+\.?\d*)[Kk]?", raw)
    if m:
        lo, hi = m.group(1), m.group(2)
        if "K" in _safe_str(raw).upper():
            lo = f"${int(float(lo) * 1000):,}"
            hi = f"${int(float(hi) * 1000):,}"
        else:
            lo = f"${int(float(lo)):,}"
            hi = f"${int(float(hi)):,}"
        return f"{lo} \u2013 {hi}/yr"
    return raw

def _parse_experience(raw: str) -> str:
    raw = _safe_str(raw)
    if not raw:
        return ""
    m = re.match(r"(\d+)\s+to\s+(\d+)\s+[Yy]ears?", raw)
    if m:
        return f"{m.group(1)}\u2013{m.group(2)} yrs"
    return raw

def _parse_benefits(raw: str) -> list[str]:
    raw = _safe_str(raw)
    if not raw:
        return []
    raw = raw.strip("{}'\"")
    return [b.strip().strip("'\"") for b in raw.split(",") if b.strip()]

def _parse_skills(raw: str) -> list[str]:
    raw = _safe_str(raw)
    if not raw:
        return []
    raw = re.sub(r"\([^)]*\)", "", raw)
    return [s.strip() for s in re.split(r"[,\n]", raw) if s.strip()]

def _parse_company_profile(raw: str) -> dict:
    raw = _safe_str(raw)
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except Exception:
        try:
            return ast.literal_eval(raw)
        except Exception:
            return {}

def _safe_json_loads(raw: str, default):
    try:
        return json.loads(raw)
    except Exception:
        return default

def _env_flag(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}

def _create_access_token(email: str, name: str, picture: str) -> str:
    if not _PYJWT_AVAILABLE:
        raise HTTPException(status_code=503, detail="PyJWT is not installed on this server")
    if not JWT_SECRET:
        raise HTTPException(status_code=503, detail="JWT_SECRET is not configured on this server")
    payload = {
        "sub": email,
        "name": name,
        "picture": picture,
        "exp": datetime.utcnow() + timedelta(hours=JWT_EXPIRE_HOURS),
    }
    return pyjwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)

def _verify_google_credential(credential: str) -> dict:
    if not _GOOGLE_AUTH_AVAILABLE:
        raise HTTPException(status_code=503, detail="google-auth is not installed on this server")
    try:
        audience = GOOGLE_CLIENT_ID or None
        token_payload = google_id_token.verify_oauth2_token(
            credential,
            google_requests.Request(),
            audience=audience,
        )
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid Google credential")
    if GOOGLE_CLIENT_ID and token_payload.get("aud") != GOOGLE_CLIENT_ID:
        raise HTTPException(status_code=401, detail="Google credential audience mismatch")
    return token_payload

def clean_row(row) -> dict:
    profile = _parse_company_profile(_safe_str(row.get("Company Profile", "")))
    skills   = _parse_skills(_safe_str(row.get("skills", "")))
    benefits = _parse_benefits(_safe_str(row.get("Benefits", "")))
    return {
        "job_id":           _safe_str(row.get("Job Id", "")),
        "title":            _safe_str(row.get("Job Title", "")),
        "role":             _safe_str(row.get("Role", "")),
        "company":          _safe_str(row.get("Company", "")),
        "location":         _safe_str(row.get("location", "")),
        "country":          _safe_str(row.get("Country", "")),
        "work_type":        _safe_str(row.get("Work Type", "")),
        "company_size":     _safe_str(row.get("Company Size", "")),
        "experience":       _parse_experience(_safe_str(row.get("Experience", ""))),
        "qualifications":   _safe_str(row.get("Qualifications", "")),
        "salary":           _parse_salary(_safe_str(row.get("Salary Range", ""))),
        "description":      _safe_str(row.get("Job Description", "")),
        "responsibilities": _safe_str(row.get("Responsibilities", "")),
        "skills":           skills,
        "benefits":         benefits,
        "sector":           profile.get("Sector", ""),
        "industry":         profile.get("Industry", ""),
        "posting_date":     _safe_str(row.get("Job Posting Date", "")),
        "portal":           _safe_str(row.get("Job Portal", "")),
    }

def job_to_text(job: dict) -> str:
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
        f"Source: {job.get('source', 'local_csv')}",
        f"URL: {job.get('external_url', '')}",
    ]
    return "\n".join(p for p in parts if not p.endswith(": "))


def _stable_job_vector_id(job: dict, fallback_idx: int) -> str:
    base_id = _safe_str(job.get("job_id"))
    if base_id:
        return f"job_{base_id}_{fallback_idx}"
    raw = (
        f"{job.get('source','local_csv')}|{job.get('title','')}|"
        f"{job.get('company','')}|{job.get('location','')}|{job.get('external_url','')}"
    )
    short_hash = hashlib.md5(raw.encode("utf-8")).hexdigest()[:16]
    return f"job_{short_hash}_{fallback_idx}"

def get_or_create_index():
    client = get_pinecone()
    existing = [idx.name for idx in client.list_indexes()]
    if PINECONE_INDEX not in existing:
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
    global _last_source_stats
    index = get_or_create_index()
    if not force:
        stats = index.describe_index_stats()
        if stats.total_vector_count > 0:
            log.info("Index already has %d vectors; skipping re-index.", stats.total_vector_count)
            return stats.total_vector_count

    mode = INDEX_MODE if INDEX_MODE in {"csv_only", "live_only", "hybrid"} else "hybrid"
    jobs: list[dict] = []

    if mode in {"csv_only", "hybrid"}:
        log.info("Loading dataset from %s ...", CSV_PATH)
        df = pd.read_csv(CSV_PATH)
        log.info("Loaded %d CSV rows.", len(df))
        jobs.extend(clean_row(df.iloc[i]) for i in range(len(df)))

    source_cfg = get_source_config()
    source_counts: dict[str, int] = {}
    external_total = 0

    if mode in {"live_only", "hybrid"}:
        external_jobs, source_counts = fetch_configured_sources_with_stats()
        external_total = sum(source_counts.values())
        if external_jobs:
            log.info("Loaded %d external listings from configured sources.", len(external_jobs))
            jobs.extend(external_jobs)
        elif mode == "live_only":
            raise RuntimeError(
                "INDEX_MODE=live_only but no external listings were fetched. "
                "Set ENABLE_EXTERNAL_SOURCES=true and configure at least one source."
            )

    if not jobs:
        raise RuntimeError(
            "No jobs available for indexing. Check INDEX_MODE, CSV_PATH, and external source config."
        )

    _last_source_stats = {
        "last_indexed_at": datetime.utcnow().isoformat() + "Z",
        "index_mode": mode,
        "external_sources_enabled": _env_flag("ENABLE_EXTERNAL_SOURCES", default=False),
        "configured_sources": source_cfg.get("enabled_sources", []),
        "india_only": source_cfg.get("india_only", True),
        "include_remote": source_cfg.get("include_remote", True),
        "source_counts": source_counts,
        "external_total": external_total,
    }

    log.info("Total listings to index: %d", len(jobs))
    EMBED_BATCH = 96
    UPSERT_BATCH = 100
    batches = [jobs[i: i + EMBED_BATCH] for i in range(0, len(jobs), EMBED_BATCH)]
    from concurrent.futures import ThreadPoolExecutor, as_completed
    all_vectors = []

    def embed_batch(batch_and_offset):
        batch, offset = batch_and_offset
        texts = [job_to_text(j) for j in batch]
        embeddings = embed_texts(texts)
        vectors = []
        for idx2, (job, emb) in enumerate(zip(batch, embeddings)):
            vid = _stable_job_vector_id(job, offset + idx2)
            meta = {
                "title": job["title"], "role": job["role"], "company": job["company"],
                "location": job["location"], "country": job["country"], "work_type": job["work_type"],
                "salary": job["salary"], "salary_min": _extract_salary_min(job["salary"]),
                "experience": job["experience"], "qualifications": job["qualifications"],
                "skills": job["skills"][:20], "benefits": job["benefits"][:10],
                "description": job["description"][:500], "responsibilities": job["responsibilities"][:300],
                "sector": job["sector"], "industry": job["industry"], "company_size": job["company_size"],
                "source": job.get("source", "local_csv"), "external_url": job.get("external_url", ""),
            }
            vectors.append({"id": vid, "values": emb, "metadata": meta})
        return vectors

    with ThreadPoolExecutor(max_workers=5) as executor:
        futures = {executor.submit(embed_batch, (batch, i * EMBED_BATCH)): i for i, batch in enumerate(batches)}
        completed = 0
        for future in as_completed(futures):
            all_vectors.extend(future.result())
            completed += 1
            log.info("Embedded %d / %d batches...", completed, len(batches))

    total = 0
    for i in range(0, len(all_vectors), UPSERT_BATCH):
        chunk = all_vectors[i: i + UPSERT_BATCH]
        index.upsert(vectors=chunk)
        total += len(chunk)
    log.info("Indexing complete. Total vectors: %d", total)
    return total

def _extract_salary_min(salary_str: str) -> float:
    m = re.search(r"\$([\d,]+)", salary_str)
    if m:
        return float(m.group(1).replace(",", ""))
    return 0.0

def _parse_salary_min_from_query(query: str) -> float:
    m = re.search(r"\$\s*([\d,]+)\s*[Kk]", query)
    if m:
        return float(m.group(1).replace(",", "")) * 1000
    m = re.search(r"\$\s*([\d,]+)", query)
    if m:
        val = float(m.group(1).replace(",", ""))
        return val * 1000 if val < 1000 else val
    m = re.search(r"\b(\d{2,3})[Kk]\b", query)
    if m:
        return float(m.group(1)) * 1000
    return 0.0

def search_jobs(query: str, top_k: int = TOP_K) -> list[dict]:
    index = get_or_create_index()
    [query_emb] = embed_texts([query])
    salary_min = _parse_salary_min_from_query(query)
    pinecone_filter = None
    if salary_min > 0:
        pinecone_filter = {"salary_min": {"$gte": salary_min}}
    results = index.query(vector=query_emb, top_k=top_k, include_metadata=True, filter=pinecone_filter)
    return [{"score": round(m.score, 4), **m.metadata} for m in results.matches]

def search_jobs_cached(query: str, top_k: int = TOP_K) -> list[dict]:
    key = hashlib.md5(f"{query}{top_k}".encode()).hexdigest()
    if key in _search_cache:
        return _search_cache[key]
    result = search_jobs(query, top_k)
    _search_cache[key] = result
    return result

# ─── LLM Prompt & Response ────────────────────────────
SYSTEM_PROMPT = """You are JobMatch AI, a precise and expert career advisor.

You will receive a user's job-seeking profile and a list of candidate job postings retrieved via semantic search. Your job is to act as a senior recruiter: critically evaluate each candidate posting against the user's profile and select the best {top_n} matches.

SCORING CRITERIA (be strict and realistic):
- 9-10: Near-perfect fit — role, skills, experience, location, and salary all align closely
- 7-8: Strong fit — most key criteria match with minor gaps
- 5-6: Moderate fit — role aligns but notable gaps in skills or experience
- 3-4: Weak fit — only surface-level match
- Do NOT inflate scores. A score of 9+ should be rare and well-justified.

OUTPUT FORMAT — follow this EXACTLY, no deviations:

# Your Job Match Results

## Summary
- Jobs Analyzed: <total count from input>
- Top Matches: {top_n}
- Best Match Score: <highest score>/10

## Top Job Matches

### <Job Title> @ <Company Name>
- **Match Score: <N>/10 | Location: <City, Country> | Salary: <range>**

**Why It Matches:**
- <Specific skill or experience from user profile that maps to this job>
- <Another concrete alignment — mention actual skill/role names>
- <Third reason — can include work type, sector, or company size fit>

**Gaps:**
- <Specific missing skill, qualification, or experience — be honest>

**Experience Alignment:** <One sentence comparing user's years/level to the job's requirement>

**Recommended Next Steps:**
1. <Concrete action specific to THIS job>
2. <Another specific action>
3. <Third action>

---

### <next job title> @ <company>
... (repeat for all {top_n} jobs)

## Recommended Next Steps
1. <Broad career advice>
2. <Skill to develop>
3. <Networking tip>

STRICT RULES:
- Use ONLY the job data provided
- Be specific: mention actual skill names, job titles, and requirements from the data
- Do NOT use emojis
- Do NOT wrap output in code fences
- Do NOT add any text before "# Your Job Match Results"
""".strip()

def build_llm_prompt(user_query: str, candidates: list[dict]) -> str:
    candidate_text = ""
    for i, c in enumerate(candidates, 1):
        skills = ", ".join(c.get("skills", [])[:12])
        benefits = ", ".join(c.get("benefits", [])[:5])
        candidate_text += (
            f"[Candidate {i}] (semantic similarity: {c['score']})\n"
            f"Title: {c.get('title', '')} | Role: {c.get('role', '')}\n"
            f"Company: {c.get('company', '')} | Sector: {c.get('sector', '')} | Industry: {c.get('industry', '')}\n"
            f"Location: {c.get('location', '')}, {c.get('country', '')} | Work Type: {c.get('work_type', '')}\n"
            f"Salary: {c.get('salary', '')} | Experience Required: {c.get('experience', '')} | Qualifications: {c.get('qualifications', '')}\n"
            f"Company Size: {c.get('company_size', '')}\n"
            f"Required Skills: {skills}\n"
            f"Benefits: {benefits}\n"
            f"Description: {c.get('description', '')[:350]}\n"
            f"Responsibilities: {c.get('responsibilities', '')[:200]}\n"
            "---\n"
        )
    return (
        f"USER PROFILE & JOB REQUEST:\n{user_query}\n\n"
        f"CANDIDATE JOB POSTINGS ({len(candidates)} retrieved by semantic search):\n"
        f"{candidate_text}\n"
        f"Select the top {TOP_N_RESULTS} best matches for this user and respond in the required Markdown format."
    )

def generate_response(user_query: str, candidates: list[dict], history: list = None) -> str:
    system = SYSTEM_PROMPT.format(top_n=TOP_N_RESULTS)
    user_msg = build_llm_prompt(user_query, candidates)
    messages = [{"role": "system", "content": system}]
    if history:
        messages.extend(history[-20:])
    messages.append({"role": "user", "content": user_msg})
    response = get_openai().chat.completions.create(
        model=CHAT_MODEL,
        messages=messages,
        temperature=0.3,
        max_tokens=3000,
    )
    return response.choices[0].message.content.strip()

# ─── Endpoints ────────────────────────────────────────

@app.get("/health")
async def health():
    return {"status": "ok", "version": "2.0.0"}


@app.post("/webhook", response_model=WebhookResponse, dependencies=[Depends(verify_api_key)])
@limiter.limit("10/minute")
async def webhook(request: Request):
    request_id = str(uuid.uuid4())[:8]
    log.info("[%s] /webhook called", request_id)

    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")

    try:
        req = WebhookRequest.model_validate(payload)
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=exc.errors())

    if req.profile:
        query = build_query_from_profile(req.profile)
    elif req.chatInput and req.chatInput.strip():
        query = req.chatInput.strip()
    else:
        raise HTTPException(status_code=400, detail="Either profile or chatInput is required")

    session_id = req.sessionId or str(uuid.uuid4())
    history = get_session_history(session_id)
    candidates = search_jobs_cached(query, top_k=TOP_K)
    if not candidates:
        return WebhookResponse(output="No matching jobs found. Please try different search terms.")
    output = generate_response(query, candidates, history)
    save_session_turn(session_id, query, output)
    log.info("[%s] /webhook done, session=%s", request_id, session_id)
    return WebhookResponse(output=output)


@app.post("/debug/retrieval", dependencies=[Depends(verify_api_key)])
@limiter.limit("20/minute")
async def debug_retrieval(request: Request, req: DebugRetrievalRequest):
    if req.profile:
        query = build_query_from_profile(req.profile)
    elif req.chatInput and req.chatInput.strip():
        query = req.chatInput.strip()
    else:
        raise HTTPException(status_code=400, detail="Either profile or chatInput is required")

    top_k = max(1, min(int(req.topK or 12), 50))
    candidates = search_jobs_cached(query, top_k=top_k)
    compact = []
    for c in candidates:
        compact.append({
            "title": c.get("title", ""),
            "company": c.get("company", ""),
            "score": c.get("score", 0),
            "semantic_score": c.get("score", 0),
            "lexical_score": 0,
            "location": c.get("location", ""),
            "country": c.get("country", ""),
            "work_type": c.get("work_type", ""),
            "salary": c.get("salary", ""),
            "skills": c.get("skills", []),
            "source": c.get("source", ""),
            "external_url": c.get("external_url", ""),
        })
    return {
        "query": query,
        "top_k": top_k,
        "count": len(compact),
        "candidates": compact,
    }


@app.post("/auth/google", dependencies=[Depends(verify_api_key)])
async def auth_google(req: GoogleAuthRequest):
    token_payload = await asyncio.to_thread(_verify_google_credential, req.credential)
    email = _safe_str(token_payload.get("email", "")).lower()
    if not email:
        raise HTTPException(status_code=401, detail="Google account email is missing")
    name = _safe_str(token_payload.get("name", "")) or email.split("@")[0]
    picture = _safe_str(token_payload.get("picture", ""))
    access_token = _create_access_token(email, name, picture)
    return {
        "status": "ok",
        "user": {"email": email, "name": name, "picture": picture},
        "email_verified": bool(token_payload.get("email_verified", True)),
        "access_token": access_token,
        "token_type": "bearer",
    }


@app.post("/index")
async def index_endpoint(force: bool = False, _: None = Depends(verify_api_key)):
    try:
        total = index_dataset(force=force)
        return {"status": "ok", "total_vectors": total, "source_stats": _last_source_stats}
    except Exception as e:
        log.exception("Indexing failed")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/sources/status")
async def sources_status(_: None = Depends(verify_api_key)):
    source_cfg = get_source_config()
    return {
        "external_sources_enabled": _env_flag("ENABLE_EXTERNAL_SOURCES", default=False),
        "configured_sources": source_cfg.get("enabled_sources", []),
        "india_only": source_cfg.get("india_only", True),
        "include_remote": source_cfg.get("include_remote", True),
        "last_index_stats": _last_source_stats,
    }


@app.post("/parse-resume", dependencies=[Depends(verify_api_key)])
async def parse_resume(file: UploadFile = File(...)):
    filename = (file.filename or "").lower()
    if not filename.endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are accepted")
    if not _PDFPLUMBER_AVAILABLE:
        raise HTTPException(status_code=503, detail="pdfplumber is not installed on this server")
    contents = await file.read()
    text = ""
    try:
        with pdfplumber.open(io.BytesIO(contents)) as pdf:
            for page in pdf.pages:
                text += (page.extract_text() or "") + "\n"
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"Could not parse PDF: {e}")

    if not text.strip():
        raise HTTPException(status_code=422, detail="No text could be extracted from PDF")

    prompt = f"""Extract structured profile information from this resume text. Return ONLY valid JSON with these exact fields:
{{
  "name": "full name or empty string",
  "email": "email address or empty string",
  "skills": ["skill1", "skill2"],
  "experience_years": 0,
  "education": "highest degree or empty string",
  "recent_role": "most recent job title or empty string",
  "industries": ["industry1"]
}}

Resume text:
{text[:3000]}"""

    response = get_openai().chat.completions.create(
        model=CHAT_MODEL,
        messages=[{"role": "user", "content": prompt}],
        temperature=0,
        max_tokens=500,
        response_format={"type": "json_object"},
    )

    try:
        parsed = json.loads(response.choices[0].message.content)
    except Exception:
        parsed = {}

    # Fallback email extraction from raw text if model misses it.
    if not _safe_str(parsed.get("email")):
        email_match = re.search(r"(?i)\b[a-z0-9._%+\-]+@[a-z0-9.\-]+\.[a-z]{2,}\b", text)
        if email_match:
            parsed["email"] = email_match.group(0)

    parsed["raw_text"] = text[:4000]
    parsed["resume_text"] = parsed["raw_text"]  # alias for compatibility
    return parsed


@app.post("/cover-letter", dependencies=[Depends(verify_api_key)])
async def generate_cover_letter(req: CoverLetterRequest):
    skills_str = ", ".join(req.profile.skills[:10]) if req.profile.skills else "various technical skills"
    prompt = f"""Write a compelling 3-paragraph cover letter for {req.profile.name or 'the applicant'} applying to the {req.jobTitle} position at {req.company}.

Applicant profile:
- Experience: {req.profile.experience} years
- Skills: {skills_str}
- Education: {req.profile.education}
- Desired role: {req.profile.desiredRole}

Job description context: {req.jobDescription[:500] if req.jobDescription else 'Not provided'}

Tone: {req.tone}

Write exactly 3 paragraphs: (1) opening hook with role and key qualification, (2) specific skills and experiences that match the role, (3) closing with enthusiasm and call to action. Do NOT include subject line, date, address blocks, or "Dear Hiring Manager" header - start directly with the first paragraph."""

    response = get_openai().chat.completions.create(
        model=CHAT_MODEL,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.7,
        max_tokens=600,
    )
    return {"cover_letter": response.choices[0].message.content.strip()}


@app.post("/bookmark", dependencies=[Depends(verify_api_key)])
async def save_bookmark(req: BookmarkRequest):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """INSERT INTO bookmarks (session_id, job_title, company, location, salary, match_score, job_data, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (req.session_id, req.job_title, req.company, req.location, req.salary,
             req.match_score, json.dumps(req.job_data), datetime.utcnow().isoformat())
        )
        await db.commit()
    return {"status": "saved"}


@app.post("/applications", dependencies=[Depends(verify_api_key)])
async def create_or_update_application(req: ApplicationCreateRequest):
    allowed_status = {"saved", "applied", "oa", "interview", "offer", "rejected"}
    status = (req.status or "saved").strip().lower()
    if status not in allowed_status:
        raise HTTPException(status_code=400, detail=f"Invalid status. Allowed: {', '.join(sorted(allowed_status))}")

    now = datetime.utcnow().isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """SELECT id, applied_at FROM applications
               WHERE session_id = ? AND job_title = ? AND company = ?
               ORDER BY id DESC LIMIT 1""",
            (req.session_id, req.job_title, req.company),
        ) as cursor:
            existing = await cursor.fetchone()

        if existing:
            applied_at = existing["applied_at"]
            if status == "applied" and not applied_at:
                applied_at = now
            await db.execute(
                """UPDATE applications
                   SET status = ?, notes = ?, applied_at = ?
                   WHERE id = ?""",
                (status, req.notes or "", applied_at, existing["id"]),
            )
            application_id = int(existing["id"])
            result_status = "updated"
        else:
            applied_at = now if status == "applied" else None
            await db.execute(
                """INSERT INTO applications (session_id, job_title, company, status, notes, applied_at, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (req.session_id, req.job_title, req.company, status, req.notes or "", applied_at, now),
            )
            async with db.execute("SELECT last_insert_rowid()") as cursor:
                row = await cursor.fetchone()
            application_id = int(row[0]) if row else None
            result_status = "saved"
        await db.commit()

    return {"status": result_status, "application_id": application_id}


@app.get("/applications/{session_id}", dependencies=[Depends(verify_api_key)])
async def get_applications(session_id: str):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """SELECT * FROM applications
               WHERE session_id = ?
               ORDER BY datetime(created_at) DESC""",
            (session_id,),
        ) as cursor:
            rows = await cursor.fetchall()
    return {"applications": [dict(row) for row in rows]}


@app.patch("/applications/{application_id}", dependencies=[Depends(verify_api_key)])
async def update_application(application_id: int, req: ApplicationUpdateRequest):
    if req.status is None and req.notes is None:
        raise HTTPException(status_code=400, detail="Provide at least one field to update")

    allowed_status = {"saved", "applied", "oa", "interview", "offer", "rejected"}
    updates = []
    params = []

    if req.status is not None:
        status = req.status.strip().lower()
        if status not in allowed_status:
            raise HTTPException(status_code=400, detail=f"Invalid status. Allowed: {', '.join(sorted(allowed_status))}")
        updates.append("status = ?")
        params.append(status)
        if status == "applied":
            updates.append("applied_at = COALESCE(applied_at, ?)")
            params.append(datetime.utcnow().isoformat())

    if req.notes is not None:
        updates.append("notes = ?")
        params.append(req.notes)

    params.append(application_id)
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            f"UPDATE applications SET {', '.join(updates)} WHERE id = ?",
            tuple(params),
        )
        await db.commit()
    if cursor.rowcount == 0:
        raise HTTPException(status_code=404, detail="Application not found")
    return {"status": "updated"}


@app.get("/bookmarks/{session_id}", dependencies=[Depends(verify_api_key)])
async def get_bookmarks(session_id: str):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM bookmarks WHERE session_id = ? ORDER BY created_at DESC",
            (session_id,)
        ) as cursor:
            rows = await cursor.fetchall()
    result = []
    for row in rows:
        item = dict(row)
        item["job_data"] = _safe_json_loads(item.get("job_data", "{}") or "{}", {})
        result.append(item)
    return {"bookmarks": result}


@app.post("/feedback", dependencies=[Depends(verify_api_key)])
async def submit_feedback(req: FeedbackRequest):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """INSERT INTO feedback (session_id, job_title, company, rating, comment, created_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (req.session_id, req.job_title, req.company, req.rating, req.comment, datetime.utcnow().isoformat())
        )
        await db.commit()
    return {"status": "ok"}


@app.post("/send-results", dependencies=[Depends(verify_api_key)])
async def send_results(req: SendResultsRequest):
    if not RESEND_API_KEY:
        raise HTTPException(status_code=503, detail="Email service not configured")
    if not _RESEND_AVAILABLE:
        raise HTTPException(status_code=503, detail="resend package is not installed on this server")
    try:
        resend_lib.api_key = RESEND_API_KEY
        # Convert simple markdown to HTML
        html_body = (
            req.results_markdown
            .replace("\n", "<br>")
            .replace("**", "<strong>")
            .replace("# ", "<h2>")
            .replace("## ", "<h3>")
        )
        resend_lib.Emails.send({
            "from": FROM_EMAIL,
            "to": req.email,
            "subject": f"Your JobMatch AI Results \u2014 {req.name}",
            "html": f"<p>Hi {req.name},</p><p>Here are your job matches:</p><br>{html_body}",
        })
        return {"status": "sent"}
    except Exception as e:
        log.exception("Email send failed")
        raise HTTPException(status_code=500, detail=f"Failed to send email: {e}")


@app.post("/enhance-resume", dependencies=[Depends(verify_api_key)])
async def enhance_resume(request: Request, file: UploadFile = File(...)):
    filename = (file.filename or "").lower()
    if not filename.endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are accepted")
    if not _PDFPLUMBER_AVAILABLE:
        raise HTTPException(status_code=503, detail="pdfplumber is not installed on this server")
    contents = await file.read()
    session_id = request.headers.get("X-Session-Id", "")
    text = ""
    try:
        with pdfplumber.open(io.BytesIO(contents)) as pdf:
            for page in pdf.pages:
                text += (page.extract_text() or "") + "\n"
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"Could not parse PDF: {e}")

    if not text.strip():
        raise HTTPException(status_code=422, detail="No text could be extracted from PDF")

    system_prompt = """You are an expert resume coach and ATS (Applicant Tracking System) optimization specialist with 15+ years reviewing resumes across technology, finance, and consulting.

Given resume text, produce a JSON audit report. Be specific — quote actual phrases from the resume. Do NOT rewrite the entire resume; produce targeted, actionable micro-improvements only.

Return ONLY valid JSON in this exact schema:
{
  "overall_score": <integer 0-100>,
  "score_breakdown": {
    "action_verbs": <0-100>,
    "quantification": <0-100>,
    "completeness": <0-100>,
    "ats_compatibility": <0-100>,
    "formatting": <0-100>
  },
  "suggestions": [
    {
      "category": "<Action Verbs|Quantification|ATS|Formatting|Missing Section|Weak Phrases>",
      "priority": "<high|medium|low>",
      "issue": "<specific problem, quote from resume if possible>",
      "fix": "<exactly what to do>",
      "example": "<before → after example>"
    }
  ],
  "ats_tips": ["<tip1>", "<tip2>"],
  "industry_tips": ["<industry-specific tip based on detected domain>"]
}

SCORING: overall_score < 50 = major issues, 50-70 = solid but improvable, 70-85 = good, 85+ = excellent.
Produce 5-8 suggestions ordered by priority (high first). Detect the likely industry from the resume and tailor industry_tips accordingly."""

    user_prompt = f"Analyze this resume:\n\n{text[:4000]}"

    response = get_openai().chat.completions.create(
        model=CHAT_MODEL,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.3,
        max_tokens=2000,
        response_format={"type": "json_object"},
    )

    try:
        result = json.loads(response.choices[0].message.content)
    except Exception:
        result = {"overall_score": 0, "suggestions": [], "ats_tips": [], "industry_tips": [], "score_breakdown": {}}

    if session_id:
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                """INSERT INTO resume_enhancements (session_id, overall_score, suggestions_json, ats_tips_json, score_breakdown_json, created_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    session_id,
                    result.get("overall_score", 0),
                    json.dumps(result.get("suggestions", [])),
                    json.dumps(result.get("ats_tips", [])),
                    json.dumps(result.get("score_breakdown", {})),
                    datetime.utcnow().isoformat(),
                )
            )
            await db.commit()

    result["raw_text"] = text[:4000]
    return result


@app.post("/tailor-resume", dependencies=[Depends(verify_api_key)])
async def tailor_resume(req: TailorResumeRequest):
    system_prompt = """You are a senior technical recruiter and resume optimization expert. Given a candidate's resume text AND a specific job description, produce a JSON report showing exactly how to tailor the resume for this particular job.

Be specific. Quote actual sentences from the resume when suggesting rewrites. Map skills in the JD directly to evidence in the resume. The score must reflect honest gap analysis.

Return ONLY valid JSON in this exact schema:
{
  "tailored_score": <integer 0-100>,
  "score_rationale": "<2-sentence explanation of the score>",
  "skills_to_add": ["<skill missing from resume but required by JD>"],
  "skills_to_emphasize": ["<skill present in resume but not prominently featured, important for JD>"],
  "bullet_rewrites": [
    {
      "original": "<exact quote from resume>",
      "rewritten": "<improved version aligned to JD>",
      "reason": "<why this change improves JD alignment>"
    }
  ],
  "priority_changes": [
    {
      "rank": <1-N>,
      "change": "<specific actionable change>",
      "impact": "<high|medium|low>",
      "section": "<Skills|Experience|Summary|Education>"
    }
  ],
  "keyword_analysis": {
    "present": ["<keywords from JD that appear in resume>"],
    "missing": ["<required JD keywords not in resume>"],
    "nice_to_have": ["<preferred JD keywords not in resume>"]
  }
}

RULES: Do NOT invent experience the candidate does not have. skills_to_add should be honest skill gaps. Produce 3-5 bullet_rewrites for the most impactful bullets. priority_changes ordered 1 = most impactful."""

    skills_str = ", ".join(req.job_skills) if req.job_skills else "not specified"
    user_prompt = f"""JOB TITLE: {req.job_title}
COMPANY: {req.company}
JOB DESCRIPTION: {req.job_description[:1000]}
JOB REQUIRED SKILLS: {skills_str}

CANDIDATE RESUME:
{req.resume_text[:4000]}"""

    response = get_openai().chat.completions.create(
        model=CHAT_MODEL,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.3,
        max_tokens=2000,
        response_format={"type": "json_object"},
    )

    try:
        result = json.loads(response.choices[0].message.content)
    except Exception:
        result = {
            "tailored_score": 0,
            "score_rationale": "Analysis could not be completed.",
            "skills_to_add": [],
            "skills_to_emphasize": [],
            "bullet_rewrites": [],
            "priority_changes": [],
            "keyword_analysis": {"present": [], "missing": [], "nice_to_have": []},
        }

    if req.session_id:
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                """INSERT INTO resume_tailoring (session_id, job_title, company, tailored_score, analysis_json, created_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    req.session_id,
                    req.job_title,
                    req.company,
                    result.get("tailored_score", 0),
                    json.dumps(result),
                    datetime.utcnow().isoformat(),
                )
            )
            await db.commit()

    return result


@app.post("/keyword-gap", dependencies=[Depends(verify_api_key)])
async def keyword_gap(req: KeywordGapRequest):
    system_prompt = """You are a resume keyword analysis system. Given resume text and a job description, extract and categorize keywords. Return ONLY valid JSON.

{
  "match_percentage": <0-100>,
  "present_keywords": ["<keywords from JD found in resume>"],
  "missing_keywords": ["<required JD keywords not in resume>"],
  "nice_to_have": ["<preferred/bonus JD keywords not in resume>"],
  "category_breakdown": {
    "technical_skills": <0-100>,
    "soft_skills": <0-100>,
    "domain_knowledge": <0-100>
  }
}

Be precise. Only list keywords that are genuinely meaningful job requirements (not filler words). Maximum 10 items per list."""

    skills_str = ", ".join(req.job_skills) if req.job_skills else ""
    user_prompt = f"""JOB DESCRIPTION: {req.job_description[:1000]}
JOB SKILLS: {skills_str}

RESUME TEXT:
{req.resume_text[:4000]}"""

    response = get_openai().chat.completions.create(
        model=CHAT_MODEL,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.1,
        max_tokens=800,
        response_format={"type": "json_object"},
    )

    try:
        return json.loads(response.choices[0].message.content)
    except Exception:
        return {
            "match_percentage": 0,
            "present_keywords": [],
            "missing_keywords": [],
            "nice_to_have": [],
            "category_breakdown": {"technical_skills": 0, "soft_skills": 0, "domain_knowledge": 0},
        }


@app.post("/compose-recruiter-email", dependencies=[Depends(verify_api_key)])
async def compose_recruiter_email(req: RecruiterEmailComposeRequest):
    profile = req.profile
    skills_str = ", ".join(req.job_skills) if req.job_skills else "not specified"
    profile_skills_str = ", ".join(profile.skills) if profile.skills else "not specified"

    recruiter_email = (req.recruiter_email or "").strip()
    if not recruiter_email:
        email_match = re.search(r"(?i)\b[a-z0-9._%+\-]+@[a-z0-9.\-]+\.[a-z]{2,}\b", req.job_description or "")
        recruiter_email = email_match.group(0) if email_match else ""

    subject = f"Application for {req.job_title} - {profile.name or 'Candidate'}"
    body = (
        f"Hi Hiring Team at {req.company},\n\n"
        f"I am interested in the {req.job_title} role and would like to be considered. "
        f"My background aligns with the role requirements and I have attached a tailored resume.\n\n"
        f"Thank you for your time. I would value the opportunity to discuss how I can contribute.\n\n"
        f"Best regards,\n{profile.name or 'Candidate'}"
    )
    tailored_resume_text = (req.resume_text or "").strip()

    system_prompt = """You are an expert recruiting communications assistant.
Return ONLY valid JSON with this exact schema:
{
  "subject": "<email subject line>",
  "body": "<plain-text outreach email body with a greeting and clear call-to-action>",
  "tailored_resume_text": "<plain-text tailored resume draft based strictly on provided resume content>"
}

Rules:
- Keep the email body concise and professional (120-220 words).
- Personalize for the role and company.
- Do not invent experience not present in the resume text.
- Tailored resume text should stay truthful and use clear section headings: Summary, Skills, Experience, Education.
- If source resume lacks a section, omit it gracefully (do not fabricate)."""

    user_prompt = f"""CANDIDATE PROFILE
Name: {profile.name or "Candidate"}
Email: {profile.email or "not provided"}
Desired Role: {profile.desiredRole or "not provided"}
Experience Years: {profile.experience}
Skills: {profile_skills_str}
Education: {profile.education or "not provided"}
Industry: {profile.industry or "not provided"}
Location: {profile.location or "not provided"}

TARGET JOB
Job Title: {req.job_title}
Company: {req.company}
Location: {req.job_location or "not specified"}
Match Score: {req.match_score if req.match_score is not None else "not provided"}
Required Skills: {skills_str}
Job Description:
{(req.job_description or "")[:1600]}

CANDIDATE RESUME TEXT
{(req.resume_text or "")[:4500]}
"""

    try:
        response = get_openai().chat.completions.create(
            model=CHAT_MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.35,
            max_tokens=2200,
            response_format={"type": "json_object"},
        )
        parsed = json.loads(response.choices[0].message.content)
        subject = _safe_str(parsed.get("subject", subject)) or subject
        body = _safe_str(parsed.get("body", body)) or body
        tailored_resume_text = _safe_str(parsed.get("tailored_resume_text", tailored_resume_text)) or tailored_resume_text
    except Exception:
        log.exception("Recruiter email composition failed, using fallback")

    safe_title = re.sub(r"[^A-Za-z0-9]+", "_", req.job_title or "Role").strip("_") or "Role"
    safe_company = re.sub(r"[^A-Za-z0-9]+", "_", req.company or "Company").strip("_") or "Company"
    tailored_resume_filename = f"Tailored_Resume_{safe_title}_{safe_company}.txt"

    gmail_params = {"view": "cm", "fs": "1", "su": subject, "body": body}
    if recruiter_email:
        gmail_params["to"] = recruiter_email
    gmail_url = "https://mail.google.com/mail/?" + urlencode(gmail_params)

    return {
        "recruiter_email": recruiter_email,
        "subject": subject,
        "body": body,
        "tailored_resume_text": tailored_resume_text,
        "tailored_resume_filename": tailored_resume_filename,
        "gmail_url": gmail_url,
    }


@app.get("/resume-enhancements/{session_id}", dependencies=[Depends(verify_api_key)])
async def get_resume_enhancements(session_id: str):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM resume_enhancements WHERE session_id = ? ORDER BY created_at DESC LIMIT 1",
            (session_id,)
        ) as cursor:
            row = await cursor.fetchone()
    if not row:
        return {"enhancement": None}
    item = dict(row)
    item["suggestions"] = _safe_json_loads(item.get("suggestions_json", "[]") or "[]", [])
    item["ats_tips"] = _safe_json_loads(item.get("ats_tips_json", "[]") or "[]", [])
    item["score_breakdown"] = _safe_json_loads(item.get("score_breakdown_json", "{}") or "{}", {})
    return {"enhancement": item}


@app.get("/resume-tailoring/{session_id}", dependencies=[Depends(verify_api_key)])
async def get_resume_tailoring(session_id: str):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM resume_tailoring WHERE session_id = ? ORDER BY created_at DESC",
            (session_id,)
        ) as cursor:
            rows = await cursor.fetchall()
    result = []
    for row in rows:
        item = dict(row)
        item["analysis"] = _safe_json_loads(item.get("analysis_json", "{}") or "{}", {})
        result.append(item)
    return {"tailoring": result}


if os.path.isdir(REACT_FRONTEND_DIR):
    @app.get("/react")
    async def react_root_redirect():
        return RedirectResponse(url="/react/")

    app.mount("/react", StaticFiles(directory=REACT_FRONTEND_DIR, html=True), name="frontend-react")
else:
    log.warning("React frontend not mounted because directory was not found: %s", REACT_FRONTEND_DIR)


@app.get("/app")
async def app_compat_redirect():
    return RedirectResponse(url="/")


@app.get("/app/")
async def app_compat_redirect_slash():
    return RedirectResponse(url="/")

if os.path.isdir(FRONTEND_DIR):
    app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")
else:
    log.warning("Frontend static files not mounted because directory was not found: %s", FRONTEND_DIR)

    @app.get("/")
    async def root_fallback():
        return {"status": "ok", "detail": "Frontend assets are not available on this deployment."}
