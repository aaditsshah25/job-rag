"""
JobMatch AI — Python Backend v2.0.0
RAG pipeline: CSV → Pinecone (embeddings) → Gemma 4 (ranking & response)

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
import html
import asyncio
import logging
import hashlib
import uuid
import io
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from typing import Optional
from urllib.parse import urlencode
from urllib.request import Request as UrlRequest, urlopen
from urllib.error import URLError, HTTPError

import pandas as pd
from fastapi import FastAPI, HTTPException, Depends, UploadFile, File, Request, Header
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, Response
from pydantic import BaseModel, ValidationError
from dotenv import load_dotenv
from openai import OpenAI
import google.generativeai as genai
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
GOOGLE_API_KEY    = os.getenv("GOOGLE_API_KEY", "")
PINECONE_API_KEY  = os.getenv("PINECONE_API_KEY", "")
PINECONE_INDEX    = os.getenv("PINECONE_INDEX", "job-listings1")
PINECONE_CLOUD    = os.getenv("PINECONE_CLOUD", "aws")
PINECONE_REGION   = os.getenv("PINECONE_REGION", "us-east-1")
EMBED_MODEL       = "text-embedding-3-small"
CHAT_MODEL        = os.getenv("GEMMA_CHAT_MODEL", "gemma-4-31b-it")
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
if _RESEND_AVAILABLE and RESEND_API_KEY:
    resend_lib.api_key = RESEND_API_KEY
GOOGLE_CLIENT_ID  = os.getenv("GOOGLE_CLIENT_ID", "")
JWT_SECRET        = os.getenv("JWT_SECRET", "").strip()
if not JWT_SECRET:
    _is_production = os.getenv("ENVIRONMENT", "").strip().lower() in ("production", "prod")
    if _is_production:
        raise RuntimeError(
            "JWT_SECRET must be set in production. "
            "Set the JWT_SECRET environment variable to a strong random secret."
        )
    JWT_SECRET = os.getenv("JWT_SECRET_FALLBACK", "jobmatch-local-dev-secret")
    log.warning("JWT_SECRET is not configured; using insecure development fallback. Set JWT_SECRET in .env for production.")
JWT_ALGORITHM     = "HS256"
JWT_EXPIRE_HOURS  = int(os.getenv("JWT_EXPIRE_HOURS", "72"))

# ─── Lazy singletons ──────────────────────────────────
_openai_client = None
_gemini_model = None
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

def get_gemini():
    global _gemini_model
    if _gemini_model is None:
        if not GOOGLE_API_KEY:
            raise RuntimeError("GOOGLE_API_KEY is not set.")
        genai.configure(api_key=GOOGLE_API_KEY)
        _gemini_model = genai.GenerativeModel(CHAT_MODEL)
    return _gemini_model

def get_pinecone() -> Pinecone:
    global _pc
    if _pc is None:
        if not PINECONE_API_KEY:
            raise RuntimeError("PINECONE_API_KEY is not set.")
        _pc = Pinecone(api_key=PINECONE_API_KEY)
    return _pc

# ─── Search cache (TTL 10 min) ────────────────────────
_search_cache: TTLCache = TTLCache(maxsize=200, ttl=600)

# ─── CSV DataFrame singleton (loaded once at startup) ─
_csv_df = None

def get_csv_df():
    global _csv_df
    if _csv_df is None:
        if os.path.exists(CSV_PATH):
            try:
                _csv_df = pd.read_csv(CSV_PATH)
            except Exception:
                _csv_df = pd.DataFrame()
        else:
            _csv_df = pd.DataFrame()
    return _csv_df

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


async def require_bearer_jwt(authorization: Optional[str] = Header(default=None)):
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing Bearer token")
    if not _PYJWT_AVAILABLE:
        raise HTTPException(status_code=503, detail="PyJWT is not installed on this server")

    token = authorization.split(" ", 1)[1].strip()
    if not token:
        raise HTTPException(status_code=401, detail="Missing Bearer token")

    try:
        payload = pyjwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    if not payload.get("sub"):
        raise HTTPException(status_code=401, detail="Invalid token payload")
    return payload

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
REACT_FRONTEND_DIR = FRONTEND_DIR  # kept for any remaining references

if _SLOWAPI_AVAILABLE:
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

_allowed_origins = os.getenv("ALLOWED_ORIGINS", "*").split(",")
_allow_credentials = _allowed_origins != ["*"]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins,
    allow_credentials=_allow_credentials,
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
    applied_at: Optional[str] = None

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
    parts = []
    if profile.desiredRole:
        parts.append(f"Role: {profile.desiredRole}")
    if profile.skills:
        parts.append(f"Skills: {', '.join(profile.skills[:12])}")
    if profile.experience:
        parts.append(f"Experience: {profile.experience} years")
    if profile.education:
        parts.append(f"Education: {profile.education}")
    if profile.industry:
        parts.append(f"Industry: {profile.industry}")
    if profile.location:
        parts.append(f"Location: {profile.location}")
    if profile.workType and profile.workType != "Any":
        parts.append(f"Work Type: {profile.workType}")
    if profile.salaryMin:
        parts.append(f"Salary Minimum: ${profile.salaryMin:,} per year")
    if profile.additional:
        parts.append(f"Preferences: {profile.additional}")
    return " | ".join(parts) if parts else "job recommendations"

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
        return {}

def _safe_json_loads(raw: str, default):
    try:
        return json.loads(raw)
    except Exception:
        return default


def _is_valid_email(email_address: str) -> bool:
    if not email_address:
        return False
    return bool(re.fullmatch(r"(?i)[a-z0-9._%+\-]+@[a-z0-9.\-]+\.[a-z]{2,}", email_address.strip()))


def _email_service_status() -> dict:
    missing = []
    if not RESEND_API_KEY:
        missing.append("RESEND_API_KEY")
    if not _RESEND_AVAILABLE:
        missing.append("resend package")
    if not _is_valid_email(FROM_EMAIL):
        missing.append("FROM_EMAIL")
    return {
        "provider": "resend",
        "configured": len(missing) == 0,
        "resend_package_available": _RESEND_AVAILABLE,
        "from_email": FROM_EMAIL,
        "missing": missing,
    }


def _markdown_to_email_html(markdown: str) -> str:
    def _inline(md_line: str) -> str:
        escaped = html.escape(md_line.strip())
        escaped = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", escaped)
        escaped = re.sub(r"`([^`]+)`", r"<code>\1</code>", escaped)
        return escaped

    lines = (markdown or "").splitlines()
    out: list[str] = []
    list_type = None
    list_items: list[str] = []

    def _flush_list():
        nonlocal list_type, list_items
        if not list_type or not list_items:
            list_type, list_items = None, []
            return
        tag = "ul" if list_type == "ul" else "ol"
        out.append(f"<{tag}>")
        out.extend(list_items)
        out.append(f"</{tag}>")
        list_type, list_items = None, []

    for raw_line in lines:
        line = raw_line.rstrip()
        stripped = line.strip()
        if not stripped:
            _flush_list()
            continue

        bullet_match = re.match(r"^[-*]\s+(.+)$", stripped)
        ordered_match = re.match(r"^\d+[.)]\s+(.+)$", stripped)

        if bullet_match:
            if list_type != "ul":
                _flush_list()
                list_type = "ul"
            list_items.append(f"<li>{_inline(bullet_match.group(1))}</li>")
            continue

        if ordered_match:
            if list_type != "ol":
                _flush_list()
                list_type = "ol"
            list_items.append(f"<li>{_inline(ordered_match.group(1))}</li>")
            continue

        _flush_list()
        if stripped.startswith("### "):
            out.append(f"<h3>{_inline(stripped[4:])}</h3>")
        elif stripped.startswith("## "):
            out.append(f"<h2>{_inline(stripped[3:])}</h2>")
        elif stripped.startswith("# "):
            out.append(f"<h1>{_inline(stripped[2:])}</h1>")
        else:
            out.append(f"<p>{_inline(stripped)}</p>")

    _flush_list()
    return "\n".join(out)


def _strip_model_json(raw: str) -> str:
    """Strip markdown code fences that Gemma/Gemini often wraps around JSON."""
    raw = raw.strip()
    # Remove ```json ... ``` or ``` ... ``` blocks
    raw = re.sub(r"^```(?:json)?\s*", "", raw, flags=re.IGNORECASE)
    raw = re.sub(r"\s*```$", "", raw)
    return raw.strip()

def _parse_model_json_or_default(raw: str, default, context: str):
    try:
        return json.loads(_strip_model_json(raw))
    except Exception as exc:
        log.warning("Invalid model JSON in %s: %s | raw snippet: %.200s", context, exc, raw)
        return default

def _env_flag(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}

def _create_access_token(email: str, name: str, picture: str) -> str:
    if not _PYJWT_AVAILABLE:
        raise HTTPException(status_code=503, detail="PyJWT is not installed on this server")
    payload = {
        "sub": email,
        "name": name,
        "picture": picture,
        "exp": datetime.utcnow() + timedelta(hours=JWT_EXPIRE_HOURS),
    }
    return pyjwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)

def _verify_google_credential(credential: str) -> dict:
    if not credential:
        raise HTTPException(status_code=401, detail="Google credential is missing")

    if _GOOGLE_AUTH_AVAILABLE:
        try:
            audience = GOOGLE_CLIENT_ID or None
            token_payload = google_id_token.verify_oauth2_token(
                credential,
                google_requests.Request(),
                audience=audience,
            )
            if GOOGLE_CLIENT_ID and token_payload.get("aud") != GOOGLE_CLIENT_ID:
                raise HTTPException(status_code=401, detail="Google credential audience mismatch")
            return token_payload
        except HTTPException:
            raise
        except Exception as _google_auth_err:
            log.error("google-auth token verification failed: %s", _google_auth_err)
            raise HTTPException(status_code=401, detail="Invalid Google credential")

    try:
        request = UrlRequest(
            "https://www.googleapis.com/oauth2/v3/userinfo",
            headers={"Authorization": f"Bearer {credential}"},
        )
        with urlopen(request, timeout=10) as response:
            token_payload = json.loads(response.read().decode("utf-8"))
        if not isinstance(token_payload, dict):
            raise ValueError("Invalid Google userinfo payload")
        return token_payload
    except (HTTPError, URLError, ValueError, json.JSONDecodeError):
        raise HTTPException(status_code=401, detail="Invalid Google credential")

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
    # Retry transient provider errors (timeouts/rate limits) to keep indexing resilient.
    max_attempts = 3
    last_error = None
    for attempt in range(1, max_attempts + 1):
        try:
            resp = get_openai().embeddings.create(model=EMBED_MODEL, input=texts)
            return [r.embedding for r in resp.data]
        except Exception as exc:
            last_error = exc
            if attempt >= max_attempts:
                break
            backoff_seconds = 1.5 ** attempt
            log.warning(
                "Embedding request failed (attempt %d/%d): %s; retrying in %.1fs",
                attempt,
                max_attempts,
                exc,
                backoff_seconds,
            )
            time.sleep(backoff_seconds)
    raise RuntimeError(f"Embedding failed after {max_attempts} attempts: {last_error}")

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
    raw = _safe_str(salary_str)
    if not raw:
        return 0.0

    normalized = raw.lower().replace(",", "")
    # Handle India notation like "12 LPA" (~12 lakh per annum).
    lpa_match = re.search(r"(\d+(?:\.\d+)?)\s*(?:lpa|lakh)", normalized)
    if lpa_match:
        return float(lpa_match.group(1)) * 100000.0

    # Capture first numeric amount and an optional K/M suffix.
    money_match = re.search(r"\$?\s*(\d+(?:\.\d+)?)\s*([kKmM]?)", normalized)
    if not money_match:
        return 0.0

    amount = float(money_match.group(1))
    unit = money_match.group(2).lower()
    if unit == "k":
        amount *= 1000.0
    elif unit == "m":
        amount *= 1000000.0
    return amount

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


def _tokenize_query(query: str) -> list[str]:
    tokens = re.findall(r"[a-zA-Z0-9+#.]{2,}", (query or "").lower())
    stop = {
        "the", "and", "for", "with", "from", "that", "this", "your", "have", "into",
        "jobs", "job", "role", "show", "find", "need", "want", "looking", "work", "remote",
        "name", "desired", "desiredrole", "skills", "skill", "experience", "years", "year",
        "education", "industry", "location", "preferred", "preference", "preferences",
        "company", "size", "benefits", "authorization", "status", "additional", "minimum",
        "salary", "profile", "recommendations", "available", "postings", "please",
    }
    return [t for t in tokens if t not in stop]


def _search_jobs_local_csv(query: str, top_k: int = TOP_K) -> list[dict]:
    df = get_csv_df()
    if df.empty:
        return []

    tokens = _tokenize_query(query)
    scored = []
    for i in range(len(df)):
        job = clean_row(df.iloc[i])
        text = " ".join([
            job.get("title", ""),
            job.get("role", ""),
            job.get("company", ""),
            job.get("location", ""),
            job.get("country", ""),
            job.get("description", ""),
            " ".join(job.get("skills", [])[:20]),
            job.get("industry", ""),
            job.get("sector", ""),
        ]).lower()
        if not tokens:
            score = 0.1
        else:
            score = sum(1 for t in tokens if t in text) / max(len(tokens), 1)
        if score > 0:
            scored.append({"score": round(float(score), 4), **job, "source": "local_csv_fallback"})

    scored.sort(key=lambda x: x.get("score", 0), reverse=True)
    return scored[: max(1, top_k)]


def _parse_pinecone_blob_text(blob_text: str) -> dict:
    text = _safe_str(blob_text)
    if not text:
        return {}

    def _extract(pattern: str) -> str:
        match = re.search(pattern, text, flags=re.IGNORECASE | re.DOTALL)
        return _safe_str(match.group(1)) if match else ""

    title = _extract(r"JOB TITLE:\s*(.*?)\s*(?:\n|$)")
    role = _extract(r"ROLE:\s*(.*?)\s*(?:\n|$)") or title
    company = _extract(r"COMPANY:\s*(.*?)\s*(?:\n|$)")
    location = _extract(r"LOCATION:\s*(.*?)\s*(?:\n|$)")
    work_type = _extract(r"WORK TYPE:\s*(.*?)\s*(?:\n|$)")
    experience = _extract(r"EXPERIENCE REQUIRED:\s*(.*?)\s*(?:\n|$)")
    salary = _extract(r"SALARY RANGE:\s*(.*?)\s*(?:\n|$)")
    qualifications = _extract(r"QUALIFICATIONS:\s*(.*?)\s*(?:\n\w+:|\Z)")
    description = _extract(r"DESCRIPTION:\s*(.*?)\s*(?:\nRESPONSIBILITIES:|\nSKILLS:|\Z)")
    responsibilities = _extract(r"RESPONSIBILITIES:\s*(.*?)\s*(?:\nSKILLS:|\Z)")
    skills = _extract(r"SKILLS:\s*(.*?)\s*(?:\Z)")

    skill_items = [s.strip() for s in re.split(r"[;,\n]", skills) if s.strip()]
    return {
        "title": title,
        "role": role,
        "company": company,
        "location": location,
        "country": "",
        "work_type": work_type,
        "salary": salary,
        "experience": experience,
        "qualifications": qualifications,
        "description": description,
        "responsibilities": responsibilities,
        "skills": skill_items,
        "benefits": [],
        "sector": "",
        "industry": "",
        "company_size": "",
        "source": "pinecone_blob",
        "external_url": "",
        "raw_text": text,
    }


def _normalize_pinecone_match(match) -> dict:
    score = round(float(getattr(match, "score", 0.0) or 0.0), 4)
    metadata = getattr(match, "metadata", {}) or {}
    if not isinstance(metadata, dict):
        metadata = {}

    normalized: dict[str, object] = {"score": score}

    if metadata.get("source") == "blob" and metadata.get("text"):
        normalized.update(_parse_pinecone_blob_text(metadata.get("text", "")))
    else:
        normalized.update(metadata)

    normalized.setdefault("title", normalized.get("role", "") or normalized.get("title", ""))
    normalized.setdefault("role", normalized.get("title", ""))
    normalized.setdefault("company", "")
    normalized.setdefault("location", "")
    normalized.setdefault("country", "")
    normalized.setdefault("work_type", "")
    normalized.setdefault("salary", "")
    normalized.setdefault("experience", "")
    normalized.setdefault("qualifications", "")
    normalized.setdefault("description", "")
    normalized.setdefault("responsibilities", "")
    normalized.setdefault("skills", [])
    normalized.setdefault("benefits", [])
    normalized.setdefault("sector", "")
    normalized.setdefault("industry", "")
    normalized.setdefault("company_size", "")
    normalized.setdefault("source", "pinecone")
    normalized.setdefault("external_url", "")

    if not isinstance(normalized.get("skills"), list):
        normalized["skills"] = _parse_skills(_safe_str(normalized.get("skills", "")))
    if not isinstance(normalized.get("benefits"), list):
        normalized["benefits"] = _parse_benefits(_safe_str(normalized.get("benefits", "")))

    return normalized

def search_jobs(query: str, top_k: int = TOP_K, profile_salary_min: Optional[int] = None) -> list[dict]:
    if not OPENAI_API_KEY or not PINECONE_API_KEY:
        return _search_jobs_local_csv(query, top_k)

    try:
        index = get_or_create_index()
        [query_emb] = embed_texts([query])
        # Prefer structured salaryMin from profile; fall back to regex extraction from query text
        salary_min = float(profile_salary_min) if profile_salary_min else _parse_salary_min_from_query(query)
        pinecone_filter = None
        if salary_min > 0:
            pinecone_filter = {"salary_min": {"$gte": salary_min}}
        results = index.query(vector=query_emb, top_k=top_k, include_metadata=True, filter=pinecone_filter)

        # Salary metadata can be missing/inconsistent (especially for live feeds).
        # If a strict salary filter wipes out retrieval, retry without the filter.
        if salary_min > 0 and not results.matches:
            log.info("Salary-filtered query returned 0 matches; retrying without salary filter")
            results = index.query(vector=query_emb, top_k=top_k, include_metadata=True)

        matches = [_normalize_pinecone_match(m) for m in results.matches]
        if matches:
            return matches

        log.info("Vector search returned 0 matches; falling back to local CSV search")
        return _search_jobs_local_csv(query, top_k)
    except Exception as exc:
        log.warning("Vector search failed, falling back to local CSV search: %s", exc)
        return _search_jobs_local_csv(query, top_k)

def search_jobs_cached(query: str, top_k: int = TOP_K, profile_salary_min: Optional[int] = None) -> list[dict]:
    key = hashlib.md5(f"{query}{top_k}{profile_salary_min}".encode()).hexdigest()
    if key in _search_cache:
        return _search_cache[key]
    result = search_jobs(query, top_k, profile_salary_min=profile_salary_min)
    _search_cache[key] = result
    return result

# ─── LLM Prompt & Response ────────────────────────────
SYSTEM_PROMPT = """You are JobMatch AI, a precise and expert career advisor.

You will receive a user's job-seeking profile and a list of candidate job postings retrieved via semantic search. Act as a senior recruiter: critically evaluate each candidate posting against the user's profile and select the best {top_n} matches.

SCORING CRITERIA (be strict and realistic):
- 9-10: Near-perfect fit — role, skills, experience, location, and salary all align closely
- 7-8: Strong fit — most key criteria match with minor gaps
- 5-6: Moderate fit — role aligns but notable gaps in skills or experience
- 3-4: Weak fit — only surface-level match
- Do NOT inflate scores. A score of 9+ should be rare and well-justified.

YOUR RESPONSE MUST START IMMEDIATELY WITH THE LINE "# Your Job Match Results" — NO preamble, NO introduction, NO thinking out loud.

OUTPUT FORMAT — copy this structure EXACTLY:

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
(repeat the exact block above for all {top_n} jobs)

## Overall Recommended Next Steps
1. <Broad career advice>
2. <Skill to develop>
3. <Networking tip>

STRICT RULES:
- Use ONLY the job data provided — do NOT invent details
- Be specific: mention actual skill names, job titles, and requirements from the data
- Do NOT use emojis
- Do NOT wrap output in markdown code fences
- Do NOT add any commentary before "# Your Job Match Results"
- Output plain markdown only — no XML tags, no JSON
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
    if not GOOGLE_API_KEY:
        top = candidates[: max(1, TOP_N_RESULTS)]
        lines = [
            "# Your Job Match Results",
            "",
            "## Summary",
            f"- Jobs Analyzed: {len(candidates)}",
            f"- Top Matches: {len(top)}",
            "",
            "## Top Job Matches",
            "",
        ]
        for c in top:
            title = c.get("title", "Unknown Role")
            company = c.get("company", "Unknown Company")
            location = ", ".join([x for x in [c.get("location", ""), c.get("country", "")] if x]) or "N/A"
            salary = c.get("salary", "Not listed")
            skills = ", ".join(c.get("skills", [])[:6]) or "Not listed"
            lines.extend([
                f"### {title} @ {company}",
                f"- Match Score: {round((c.get('score', 0) or 0) * 10, 1)}/10",
                f"- Location: {location}",
                f"- Salary: {salary}",
                f"- Skills: {skills}",
                "",
            ])
        lines.extend([
            "## Note",
            "- Running in basic mode without API key. Results are keyword-based from the local dataset.",
        ])
        return "\n".join(lines)

    system = SYSTEM_PROMPT.format(top_n=TOP_N_RESULTS)
    user_msg = build_llm_prompt(user_query, candidates)
    # Build history for Gemini chat
    chat_history = []
    if history:
        for msg in history[-20:]:
            role = "user" if msg.get("role") == "user" else "model"
            chat_history.append({"role": role, "parts": [msg.get("content", "")]})
    full_prompt = f"{system}\n\n{user_msg}"
    model = get_gemini()
    chat = model.start_chat(history=chat_history)
    response = chat.send_message(
        full_prompt,
        generation_config=genai.types.GenerationConfig(temperature=0.3, max_output_tokens=4096),
    )
    text = response.text.strip()
    # Strip any preamble before the expected heading (Gemma sometimes adds intro text)
    marker = "# Your Job Match Results"
    idx = text.find(marker)
    if idx > 0:
        text = text[idx:]
    return text

# ─── Endpoints ────────────────────────────────────────

@app.get("/health")
async def health():
    return {"status": "ok", "version": "2.0.0"}


@app.get("/auth/config")
async def auth_config():
    return {
        "googleClientId": GOOGLE_CLIENT_ID,
        "googleAuthEnabled": bool(GOOGLE_CLIENT_ID),
    }


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
    profile_salary_min = req.profile.salaryMin if req.profile else None
    candidates = search_jobs_cached(query, top_k=TOP_K, profile_salary_min=profile_salary_min)
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
    profile_salary_min = req.profile.salaryMin if req.profile else None
    candidates = search_jobs_cached(query, top_k=top_k, profile_salary_min=profile_salary_min)
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


@app.post("/auth/google")
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


MAX_RESUME_BYTES = int(os.getenv("MAX_RESUME_BYTES", str(8 * 1024 * 1024)))  # 8 MB default

@app.post("/parse-resume", dependencies=[Depends(verify_api_key)])
async def parse_resume(file: UploadFile = File(...)):
    filename = (file.filename or "").lower()
    if not filename.endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are accepted")
    if not _PDFPLUMBER_AVAILABLE:
        raise HTTPException(status_code=503, detail="pdfplumber is not installed on this server")
    contents = await file.read()
    if len(contents) > MAX_RESUME_BYTES:
        raise HTTPException(status_code=413, detail=f"File too large. Maximum size is {MAX_RESUME_BYTES // (1024 * 1024)} MB")
    if not contents[:5] == b"%PDF-":
        raise HTTPException(status_code=400, detail="Uploaded file is not a valid PDF")
    text = ""
    try:
        with pdfplumber.open(io.BytesIO(contents)) as pdf:
            for page in pdf.pages:
                text += (page.extract_text() or "") + "\n"
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"Could not parse PDF: {e}")

    if not text.strip():
        raise HTTPException(status_code=422, detail="No text could be extracted from PDF")

    if not GOOGLE_API_KEY:
        found_email = re.search(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", text)
        known_skills = [
            "python", "sql", "excel", "power bi", "tableau", "java", "javascript", "react",
            "node", "machine learning", "deep learning", "nlp", "fastapi", "django", "aws", "azure",
        ]
        lower_text = text.lower()
        extracted_skills = [s for s in known_skills if s in lower_text]
        lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
        possible_name = lines[0][:80] if lines else ""
        years = re.findall(r"(\d+)\+?\s*(?:years?|yrs?)", lower_text)
        experience_years = int(years[0]) if years else 0
        return {
            "name": possible_name,
            "skills": extracted_skills,
            "experience_years": experience_years,
            "education": "",
            "recent_role": "",
            "industries": [],
            "email": found_email.group(0) if found_email else "",
            "raw_text": text[:4000],
            "resume_text": text[:4000],
            "mode": "basic",
        }

    prompt = f"""Extract structured profile information from this resume text. Return ONLY valid JSON — no markdown fences, no explanation, no extra text. Use these exact fields:
{{
  "name": "full name or empty string",
  "skills": ["skill1", "skill2"],
  "experience_years": 0,
  "education": "highest degree or empty string",
  "recent_role": "most recent job title or empty string",
  "industries": ["industry1"]
}}

Resume text:
{text[:3000]}"""

    model = get_gemini()
    response = model.generate_content(
        prompt,
        generation_config=genai.types.GenerationConfig(temperature=0, max_output_tokens=500),
    )

    parsed = _parse_model_json_or_default(
        response.text,
        {},
        "parse_resume",
    )

    parsed["raw_text"] = text[:4000]
    parsed["resume_text"] = parsed["raw_text"]  # alias for compatibility
    return parsed


@app.post("/cover-letter", dependencies=[Depends(verify_api_key)])
async def generate_cover_letter(req: CoverLetterRequest):
    skills_str = ", ".join(req.profile.skills[:10]) if req.profile.skills else "various technical skills"
    if not GOOGLE_API_KEY:
        applicant = req.profile.name or "the candidate"
        role = req.jobTitle or "the role"
        company = req.company or "your company"
        tone = (req.tone or "professional").strip().lower()
        opener = {
            "friendly": f"I am excited to apply for the {role} position at {company}.",
            "concise": f"I am applying for the {role} role at {company}.",
        }.get(tone, f"I am writing to express my interest in the {role} position at {company}.")
        body = (
            f"{opener}\n\n"
            f"I bring {max(req.profile.experience, 0)} years of experience and practical skills in {skills_str}. "
            f"My background aligns well with the responsibilities typically expected for this role. "
            f"I focus on reliable execution, clear communication, and measurable outcomes.\n\n"
            f"Thank you for considering {applicant}. I would value the chance to discuss how I can contribute to {company}."
        )
        return {"cover_letter": body, "mode": "basic"}

    prompt = f"""Write a compelling 3-paragraph cover letter for {req.profile.name or 'the applicant'} applying to the {req.jobTitle} position at {req.company}.

Applicant profile:
- Experience: {req.profile.experience} years
- Skills: {skills_str}
- Education: {req.profile.education}
- Desired role: {req.profile.desiredRole}

Job description context: {req.jobDescription[:500] if req.jobDescription else 'Not provided'}

Tone: {req.tone}

Write exactly 3 paragraphs: (1) opening hook with role and key qualification, (2) specific skills and experiences that match the role, (3) closing with enthusiasm and call to action. Do NOT include subject line, date, address blocks, or "Dear Hiring Manager" header - start directly with the first paragraph."""

    model = get_gemini()
    response = model.generate_content(
        prompt,
        generation_config=genai.types.GenerationConfig(temperature=0.7, max_output_tokens=600),
    )
    return {"cover_letter": response.text.strip()}


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
    allowed_status = {"saved", "applied", "interviewing", "offered", "rejected"}
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


@app.get("/applications/check", dependencies=[Depends(verify_api_key), Depends(require_bearer_jwt)])
async def check_application_exists(session_id: str, job_title: str, company: str):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """SELECT * FROM applications
               WHERE session_id = ? AND job_title = ? AND company = ?
               ORDER BY id DESC LIMIT 1""",
            (session_id, job_title, company),
        ) as cursor:
            row = await cursor.fetchone()

    if not row:
        return {"exists": False, "application": None}

    return {"exists": True, "application": dict(row)}


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
    if req.status is None and req.notes is None and req.applied_at is None:
        raise HTTPException(status_code=400, detail="Provide at least one field to update")

    allowed_status = {"saved", "applied", "interviewing", "offered", "rejected"}
    # Whitelist maps field → exact SQL clause to prevent any f-string injection
    _ALLOWED_CLAUSES = {
        "status": "status = ?",
        "notes": "notes = ?",
        "applied_at": "applied_at = ?",
        "applied_at_coalesce": "applied_at = COALESCE(applied_at, ?)",
    }
    updates = []
    params = []

    if req.status is not None:
        status = req.status.strip().lower()
        if status not in allowed_status:
            raise HTTPException(status_code=400, detail=f"Invalid status. Allowed: {', '.join(sorted(allowed_status))}")
        updates.append(_ALLOWED_CLAUSES["status"])
        params.append(status)
        if status == "applied":
            updates.append(_ALLOWED_CLAUSES["applied_at_coalesce"])
            params.append(datetime.utcnow().isoformat())

    if req.notes is not None:
        updates.append(_ALLOWED_CLAUSES["notes"])
        params.append(req.notes)

    if req.applied_at is not None:
        updates.append(_ALLOWED_CLAUSES["applied_at"])
        params.append(req.applied_at)

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


@app.delete("/bookmarks/{bookmark_id}", dependencies=[Depends(verify_api_key), Depends(require_bearer_jwt)])
async def delete_bookmark(bookmark_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("DELETE FROM bookmarks WHERE id = ?", (bookmark_id,))
        await db.commit()
    if cursor.rowcount == 0:
        raise HTTPException(status_code=404, detail="Bookmark not found")
    return {"message": "Deleted successfully"}


@app.delete("/applications/{application_id}", dependencies=[Depends(verify_api_key), Depends(require_bearer_jwt)])
async def delete_application(application_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("DELETE FROM applications WHERE id = ?", (application_id,))
        await db.commit()
    if cursor.rowcount == 0:
        raise HTTPException(status_code=404, detail="Application not found")
    return {"message": "Deleted successfully"}


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


@app.get("/email/status", dependencies=[Depends(verify_api_key)])
async def email_status():
    return _email_service_status()


@app.post("/send-results", dependencies=[Depends(verify_api_key)])
async def send_results(req: SendResultsRequest):
    status = _email_service_status()
    if not status["configured"]:
        missing = ", ".join(status["missing"]) if status["missing"] else "unknown configuration"
        raise HTTPException(status_code=503, detail=f"Email service not configured: {missing}")

    recipient = (req.email or "").strip().lower()
    recipient_name = (req.name or "").strip() or "there"
    if not _is_valid_email(recipient):
        raise HTTPException(status_code=422, detail="Please provide a valid recipient email address")
    if not (req.results_markdown or "").strip():
        raise HTTPException(status_code=422, detail="No results available to email")

    try:
        html_body = _markdown_to_email_html(req.results_markdown)
        email_html = (
            "<div style='font-family:Arial,sans-serif;max-width:760px;margin:0 auto;color:#0f172a;'>"
            f"<p>Hi {html.escape(recipient_name)},</p>"
            "<p>Here are your latest job matches from JobMatch AI.</p>"
            "<div style='background:#f8fafc;border:1px solid #e2e8f0;border-radius:10px;padding:16px 18px;'>"
            f"{html_body}"
            "</div>"
            "<p style='margin-top:18px;'>Best,<br/>JobMatch AI</p>"
            "</div>"
        )
        resend_lib.Emails.send({
            "from": FROM_EMAIL,
            "to": recipient,
            "subject": f"Your JobMatch AI Results \u2014 {recipient_name}",
            "html": email_html,
            "text": f"Hi {recipient_name},\n\nHere are your job matches:\n\n{req.results_markdown}",
        })
        return {"status": "sent", "to": recipient, "provider": status["provider"]}
    except Exception:
        log.exception("Email send failed")
        raise HTTPException(status_code=500, detail="Email delivery failed. Please try again.")


@app.post("/enhance-resume", dependencies=[Depends(verify_api_key)])
async def enhance_resume(request: Request, file: UploadFile = File(...)):
    filename = (file.filename or "").lower()
    if not filename.endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are accepted")
    if not _PDFPLUMBER_AVAILABLE:
        raise HTTPException(status_code=503, detail="pdfplumber is not installed on this server")
    contents = await file.read()
    if len(contents) > MAX_RESUME_BYTES:
        raise HTTPException(status_code=413, detail=f"File too large. Maximum size is {MAX_RESUME_BYTES // (1024 * 1024)} MB")
    if not contents[:5] == b"%PDF-":
        raise HTTPException(status_code=400, detail="Uploaded file is not a valid PDF")
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

Return ONLY valid JSON in this exact schema — no markdown code fences, no explanation, no extra text before or after the JSON:
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

    model = get_gemini()
    response = model.generate_content(
        f"{system_prompt}\n\n{user_prompt}",
        generation_config=genai.types.GenerationConfig(temperature=0.3, max_output_tokens=2000),
    )

    result = _parse_model_json_or_default(
        response.text,
        {"overall_score": 0, "suggestions": [], "ats_tips": [], "industry_tips": [], "score_breakdown": {}},
        "enhance_resume",
    )

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

Return ONLY valid JSON in this exact schema — no markdown code fences, no explanation, no extra text before or after the JSON:
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

    model = get_gemini()
    response = model.generate_content(
        f"{system_prompt}\n\n{user_prompt}",
        generation_config=genai.types.GenerationConfig(temperature=0.3, max_output_tokens=2000),
    )

    result = _parse_model_json_or_default(
        response.text,
        {
            "tailored_score": 0,
            "score_rationale": "Analysis could not be completed.",
            "skills_to_add": [],
            "skills_to_emphasize": [],
            "bullet_rewrites": [],
            "priority_changes": [],
            "keyword_analysis": {"present": [], "missing": [], "nice_to_have": []},
        },
        "tailor_resume",
    )

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
    system_prompt = """You are a resume keyword analysis system. Given resume text and a job description, extract and categorize keywords. Return ONLY valid JSON — no markdown code fences, no explanation, no extra text.

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

    model = get_gemini()
    response = model.generate_content(
        f"{system_prompt}\n\n{user_prompt}",
        generation_config=genai.types.GenerationConfig(temperature=0.1, max_output_tokens=800),
    )

    return _parse_model_json_or_default(
        response.text,
        {
            "match_percentage": 0,
            "present_keywords": [],
            "missing_keywords": [],
            "nice_to_have": [],
            "category_breakdown": {"technical_skills": 0, "soft_skills": 0, "domain_knowledge": 0},
        },
        "keyword_gap",
    )


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
Return ONLY valid JSON with this exact schema — no markdown code fences, no explanation, no extra text before or after the JSON:
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
        model = get_gemini()
        response = model.generate_content(
            f"{system_prompt}\n\n{user_prompt}",
            generation_config=genai.types.GenerationConfig(temperature=0.35, max_output_tokens=2200),
        )
        parsed = _parse_model_json_or_default(response.text, {}, "compose_recruiter_email")
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
async def get_resume_tailoring(session_id: str, page: int = 0):
    limit = 50
    offset = page * limit
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM resume_tailoring WHERE session_id = ? ORDER BY created_at DESC LIMIT ? OFFSET ?",
            (session_id, limit, offset)
        ) as cursor:
            rows = await cursor.fetchall()
    result = []
    for row in rows:
        item = dict(row)
        item["analysis"] = _safe_json_loads(item.get("analysis_json", "{}") or "{}", {})
        result.append(item)
    return {"tailoring": result, "page": page}


@app.get("/jobs/browse", dependencies=[Depends(verify_api_key)])
@limiter.limit("30/minute")
async def browse_jobs(
    request: Request,
    q: str = "",
    work_type: str = "",
    location: str = "",
    page: int = 0,
    page_size: int = 20,
):
    """Return a paginated list of jobs from the index without requiring a user profile."""
    query = q.strip() if q.strip() else "software engineer developer analyst"
    top_k = min(100, max(page_size, 50))
    candidates = search_jobs_cached(query, top_k=top_k)

    # Apply optional filters
    if work_type:
        wt_lower = work_type.lower()
        candidates = [c for c in candidates if wt_lower in (c.get("work_type") or "").lower()]
    if location:
        loc_lower = location.lower()
        candidates = [
            c for c in candidates
            if loc_lower in (c.get("location") or "").lower()
            or loc_lower in (c.get("country") or "").lower()
        ]

    total = len(candidates)
    start = page * page_size
    page_jobs = candidates[start: start + page_size]

    results = []
    for job in page_jobs:
        results.append({
            "title": job.get("title", ""),
            "company": job.get("company", ""),
            "location": job.get("location", ""),
            "country": job.get("country", ""),
            "work_type": job.get("work_type", ""),
            "salary": job.get("salary", ""),
            "experience": job.get("experience", ""),
            "skills": job.get("skills", [])[:10],
            "description": (job.get("description") or "")[:300],
            "industry": job.get("industry", ""),
            "source": job.get("source", ""),
            "external_url": job.get("external_url", ""),
            "score": job.get("score", 0),
        })

    return {
        "jobs": results,
        "total": total,
        "page": page,
        "page_size": page_size,
        "has_more": (start + page_size) < total,
    }


# ── Serve frontend/ at / and /dashboard ───────────────────────────────────
if os.path.isdir(FRONTEND_DIR):
    app.mount("/dashboard", StaticFiles(directory=FRONTEND_DIR, html=True), name="dashboard")
    app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="root")
    log.info("Frontend mounted at / and /dashboard from %s", FRONTEND_DIR)
else:
    log.warning("Frontend directory not found: %s", FRONTEND_DIR)

    @app.get("/")
    async def root_fallback():
        return {"status": "ok", "version": "2.0.0"}
