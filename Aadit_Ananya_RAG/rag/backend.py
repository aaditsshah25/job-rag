"""
JobMatch AI — Python Backend v2.0.0
RAG pipeline: CSV → Pinecone (embeddings) → GPT-4o (ranking & response)

Endpoints:
  POST /webhook          — accepts {profile, sessionId} or {chatInput, sessionId}
  GET  /health           — health check
  POST /index            — (re)index the CSV dataset into Pinecone
  POST /parse-resume     — extract structured profile from PDF resume
    POST /resume-tailor    — generate tailored resume bullets for a selected job
  POST /cover-letter     — generate a tailored cover letter
    POST /interview-prep   — generate interview prep based on tracked application stage
  POST /bookmark         — save a bookmarked job
  GET  /bookmarks/{sid}  — retrieve bookmarks for a session
  POST /feedback         — submit job rating/feedback
    POST /alerts/run       — manually trigger alert digest sending
  POST /send-results     — email results via Resend API
"""

from __future__ import annotations

import os
import re
import json
import math
import ast
import html as html_lib
import asyncio
import logging
import hashlib
import uuid
import io
import urllib.request
import urllib.parse
import urllib.error
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from typing import Optional

import pandas as pd
from fastapi import FastAPI, HTTPException, Depends, UploadFile, File, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ValidationError
from dotenv import load_dotenv
from openai import OpenAI
from pinecone import Pinecone, ServerlessSpec
from cachetools import TTLCache
import aiosqlite
from source_ingestion import fetch_configured_sources

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
    resend_lib = None

try:
    from apscheduler.schedulers.asyncio import AsyncIOScheduler
    from apscheduler.triggers.cron import CronTrigger
    _APSCHEDULER_AVAILABLE = True
except ImportError:
    _APSCHEDULER_AVAILABLE = False

try:
    from jose import jwt as jose_jwt, JWTError
    _JOSE_AVAILABLE = True
except ImportError:
    _JOSE_AVAILABLE = False

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
GOOGLE_CLIENT_ID  = os.getenv("GOOGLE_CLIENT_ID", "")
CSV_PATH          = os.getenv(
    "CSV_PATH",
    os.path.join(os.path.dirname(__file__), "GENAI_RAG_Dataset - Sheet1.csv")
)
DB_PATH           = os.getenv("DB_PATH", "./data/jobmatch.db")
JOBMATCH_API_KEY  = os.getenv("JOBMATCH_API_KEY", "")
RESEND_API_KEY    = os.getenv("RESEND_API_KEY", "")
FROM_EMAIL        = os.getenv("FROM_EMAIL", "noreply@jobmatchai.dev")
JWT_SECRET        = os.getenv("JWT_SECRET", "change-me-in-production")
JWT_ALGORITHM     = "HS256"
JWT_EXPIRE_HOURS  = int(os.getenv("JWT_EXPIRE_HOURS", "72"))
INDEX_ON_STARTUP  = os.getenv("INDEX_ON_STARTUP", "").strip().lower() in {"1", "true", "yes", "on"}


def _cors_allowlist() -> list[str]:
    return ["*"]

# ─── Lazy singletons ──────────────────────────────────
_openai_client = None
_pc = None

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

# ─── JWT helpers ──────────────────────────────────────
def _create_jwt(email: str, name: str, picture: str) -> str:
    if not _JOSE_AVAILABLE:
        return ""
    if not JWT_SECRET or JWT_SECRET == "change-me-in-production":
        raise HTTPException(status_code=500, detail="JWT_SECRET must be configured when Google sign-in is enabled")
    expire = datetime.utcnow() + timedelta(hours=JWT_EXPIRE_HOURS)
    payload = {"sub": email, "name": name, "picture": picture, "exp": expire}
    return jose_jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)

def _decode_jwt(token: str) -> dict:
    if not _JOSE_AVAILABLE:
        raise HTTPException(status_code=503, detail="JWT library not available")
    try:
        return jose_jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    except JWTError as exc:
        raise HTTPException(status_code=401, detail=f"Invalid or expired token: {exc}")

async def verify_jwt(request: Request):
    """Dependency: verifies Bearer JWT. Only enforced when GOOGLE_CLIENT_ID is set."""
    if not GOOGLE_CLIENT_ID:
        return  # auth not configured — open access
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing Authorization header")
    token = auth_header[7:]
    _decode_jwt(token)

# ─── Database init ────────────────────────────────────
async def _ensure_column(db: aiosqlite.Connection, table_name: str, column_name: str, column_ddl: str):
    async with db.execute(f"PRAGMA table_info({table_name})") as cursor:
        cols = await cursor.fetchall()
    existing = {c[1] for c in cols}
    if column_name not in existing:
        await db.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_ddl}")


def _sanitize_text(value: str) -> str:
    return html_lib.escape(_safe_str(value))


async def _send_email_html(to_email: str, subject: str, html_body: str) -> bool:
    if not RESEND_API_KEY or not _RESEND_AVAILABLE or resend_lib is None:
        return False

    try:
        resend_lib.api_key = RESEND_API_KEY
        resend_lib.Emails.send({
            "from": FROM_EMAIL,
            "to": to_email,
            "subject": subject,
            "html": html_body,
        })
        return True
    except Exception:
        log.exception("Email send failed for %s", to_email)
        return False


async def _send_confirmation_email(email: str, name: str, message: str, subject: str) -> bool:
    safe_name = _sanitize_text(name or email or "there")
    safe_message = _sanitize_text(message)
    body = f"<p>Hi {safe_name},</p><p>{safe_message}</p><p>If you did not request this, you can ignore this email.</p>"
    return await _send_email_html(email, subject, body)


async def _upsert_user_profile(
    *,
    email: str,
    name: str = "",
    google_sub: str = "",
    picture: str = "",
    profile: Optional[UserProfile] = None,
    send_confirmation: bool = False,
) -> dict:
    normalized_email = _safe_str(email).lower()
    if not normalized_email:
        raise HTTPException(status_code=400, detail="email is required")

    now = datetime.utcnow().isoformat()
    profile_json = profile.model_dump_json() if profile else None

    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            INSERT INTO users (
                email, google_sub, name, picture, profile_json,
                created_at, updated_at, last_login_at, login_count
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1)
            ON CONFLICT(email) DO UPDATE SET
                google_sub = COALESCE(excluded.google_sub, users.google_sub),
                name = COALESCE(excluded.name, users.name),
                picture = COALESCE(excluded.picture, users.picture),
                profile_json = COALESCE(excluded.profile_json, users.profile_json),
                updated_at = excluded.updated_at,
                last_login_at = excluded.last_login_at,
                login_count = COALESCE(users.login_count, 0) + 1
            """,
            (
                normalized_email,
                google_sub or None,
                name or normalized_email.split("@")[0],
                picture or None,
                profile_json,
                now,
                now,
                now,
            ),
        )
        await db.commit()

    confirmation_sent = False
    if send_confirmation:
        confirmation_sent = await _send_confirmation_email(
            normalized_email,
            name or normalized_email.split("@")[0],
            "Your JobMatch AI profile is ready and your account is active.",
            "JobMatch AI profile confirmation",
        )

    return {
        "email": normalized_email,
        "name": name or normalized_email.split("@")[0],
        "google_sub": google_sub,
        "picture": picture,
        "profile": profile.model_dump() if profile else None,
        "confirmation_sent": confirmation_sent,
    }


def _verify_google_id_token_sync(id_token: str) -> dict:
    if not GOOGLE_CLIENT_ID:
        raise HTTPException(status_code=503, detail="GOOGLE_CLIENT_ID is not configured")

    token = _safe_str(id_token)
    if not token:
        raise HTTPException(status_code=400, detail="Google credential is required")

    url = f"https://oauth2.googleapis.com/tokeninfo?id_token={urllib.parse.quote(token)}"
    try:
        with urllib.request.urlopen(url, timeout=10) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="ignore") if hasattr(exc, "read") else str(exc)
        raise HTTPException(status_code=401, detail=f"Google token verification failed: {detail}")
    except Exception as exc:
        raise HTTPException(status_code=401, detail=f"Google token verification failed: {exc}")

    if payload.get("aud") != GOOGLE_CLIENT_ID:
        raise HTTPException(status_code=401, detail="Google token audience mismatch")

    email_verified = str(payload.get("email_verified", "false")).lower() == "true"
    if not email_verified:
        raise HTTPException(status_code=401, detail="Google email is not verified")

    return payload


async def init_db():
    os.makedirs(os.path.dirname(os.path.abspath(DB_PATH)), exist_ok=True)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                email TEXT PRIMARY KEY,
                google_sub TEXT,
                name TEXT,
                picture TEXT,
                profile_json TEXT,
                created_at TEXT,
                updated_at TEXT,
                last_login_at TEXT,
                login_count INTEGER DEFAULT 1
            )
        """)
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
                location TEXT,
                salary TEXT,
                source TEXT,
                applied_at TEXT,
                updated_at TEXT,
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
        await _ensure_column(db, "users", "google_sub", "TEXT")
        await _ensure_column(db, "users", "name", "TEXT")
        await _ensure_column(db, "users", "picture", "TEXT")
        await _ensure_column(db, "users", "profile_json", "TEXT")
        await _ensure_column(db, "users", "created_at", "TEXT")
        await _ensure_column(db, "users", "updated_at", "TEXT")
        await _ensure_column(db, "users", "last_login_at", "TEXT")
        await _ensure_column(db, "users", "login_count", "INTEGER DEFAULT 1")
        # Lightweight migrations for existing DB files.
        await _ensure_column(db, "applications", "location", "TEXT")
        await _ensure_column(db, "applications", "salary", "TEXT")
        await _ensure_column(db, "applications", "source", "TEXT")
        await _ensure_column(db, "applications", "updated_at", "TEXT")
        await db.commit()


def _match_digest_html(name: str, matches: list[dict], frequency: str) -> str:
    items = []
    for m in matches[:TOP_N_RESULTS]:
        title = _safe_str(m.get("title", "Untitled Role"))
        company = _safe_str(m.get("company", "Unknown Company"))
        location = _safe_str(m.get("location", ""))
        salary = _safe_str(m.get("salary", ""))
        score = m.get("score", 0)
        meta = " | ".join(x for x in [location, salary] if x)
        items.append(f"<li><strong>{title}</strong> @ {company} (similarity: {score})<br>{meta}</li>")

    if not items:
        items = ["<li>No strong matches found this cycle. We will try again next run.</li>"]

    title = "Daily" if frequency == "daily" else "Weekly"
    return (
        f"<p>Hi {name or 'there'},</p>"
        f"<p>Here are your {title.lower()} curated JobMatch AI recommendations:</p>"
        f"<ol>{''.join(items)}</ol>"
        "<p>Open the app to track these roles and generate tailored assets.</p>"
    )


async def run_alert_digests(frequency: str = "auto") -> dict:
    if frequency not in {"auto", "daily", "weekly"}:
        raise ValueError("frequency must be auto, daily, or weekly")

    if not _RESEND_AVAILABLE or resend_lib is None or not RESEND_API_KEY:
        return {"status": "skipped", "detail": "Email service not configured", "processed": 0, "sent": 0}

    weekday = datetime.utcnow().weekday()
    resend_lib.api_key = RESEND_API_KEY

    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM alert_subscriptions WHERE active = 1"
        ) as cursor:
            rows = await cursor.fetchall()

    processed = 0
    sent = 0
    errors = 0

    for row in rows:
        sub_freq = _safe_str(row["frequency"]).lower() or "weekly"
        should_send = False

        if frequency == "daily":
            should_send = sub_freq == "daily"
        elif frequency == "weekly":
            should_send = sub_freq == "weekly"
        else:
            should_send = (sub_freq == "daily") or (sub_freq == "weekly" and weekday == 0)

        if not should_send:
            continue

        processed += 1
        try:
            profile_dict = json.loads(row["profile_json"] or "{}")
            profile = UserProfile.model_validate(profile_dict)
            query = build_query_from_profile(profile)
            matches = search_jobs_cached(query, top_k=TOP_K)
            html = _match_digest_html(_safe_str(row["name"]), matches, sub_freq)

            resend_lib.Emails.send({
                "from": FROM_EMAIL,
                "to": row["email"],
                "subject": f"JobMatch AI {sub_freq.capitalize()} Digest",
                "html": html,
            })
            sent += 1
        except Exception:
            errors += 1
            log.exception("Failed alert digest send for %s", row["email"])

    return {"status": "ok", "processed": processed, "sent": sent, "errors": errors, "frequency": frequency}


async def _scheduled_alert_digest_job():
    try:
        result = await run_alert_digests("auto")
        log.info("Scheduled alert digest run: %s", result)
    except Exception:
        log.exception("Scheduled alert digest run failed")

# ─── Lifespan ─────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()

    scheduler = None
    if _APSCHEDULER_AVAILABLE:
        scheduler = AsyncIOScheduler(timezone="UTC")
        scheduler.add_job(_scheduled_alert_digest_job, CronTrigger(hour=8, minute=0), id="jobmatch_alert_digest", replace_existing=True)
        scheduler.start()

    if INDEX_ON_STARTUP and OPENAI_API_KEY and PINECONE_API_KEY:
        try:
            index_dataset(force=False)
        except Exception as e:
            log.error("Auto-index failed: %s", e)
    elif INDEX_ON_STARTUP:
        log.warning("INDEX_ON_STARTUP is enabled, but OPENAI_API_KEY or PINECONE_API_KEY is missing; skipping auto-index.")

    app.state.scheduler = scheduler
    yield

    if scheduler:
        scheduler.shutdown(wait=False)

# ─── FastAPI App ──────────────────────────────────────
app = FastAPI(title="JobMatch AI Backend", version="2.0.0", lifespan=lifespan)

if _SLOWAPI_AVAILABLE:
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_allowlist(),
    allow_credentials=False,
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
    sessionId: Optional[str] = None
    topMatches: list[dict] = []

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
    profile: Optional[UserProfile] = None


class ProfileUpsertRequest(BaseModel):
    email: str
    name: str = ""
    google_sub: str = ""
    picture: str = ""
    profile: UserProfile
    send_confirmation: bool = True


class ApplicationCreateRequest(BaseModel):
    session_id: str
    job_title: str
    company: str
    location: str = ""
    salary: str = ""
    source: str = "jobmatch"
    notes: str = ""


class ApplicationUpdateRequest(BaseModel):
    status: Optional[str] = None
    notes: Optional[str] = None


class AlertSubscriptionRequest(BaseModel):
    email: str
    name: str = ""
    profile: UserProfile
    frequency: str = "weekly"


class AlertSubscriptionUpdateRequest(BaseModel):
    active: bool


class ScoreBreakdownRequest(BaseModel):
    profile: UserProfile
    job: dict


class ResumeTailorRequest(BaseModel):
    profile: UserProfile
    jobTitle: str
    company: str
    jobDescription: str = ""
    currentResumeText: str = ""
    focusAreas: list[str] = []


class InterviewPrepRequest(BaseModel):
    application_id: int
    profile: Optional[UserProfile] = None
    focus: str = ""


class AlertRunRequest(BaseModel):
    frequency: str = "auto"  # auto | daily | weekly

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
    index = get_or_create_index()
    if not force:
        stats = index.describe_index_stats()
        if stats.total_vector_count > 0:
            log.info("Index already has %d vectors; skipping re-index.", stats.total_vector_count)
            return stats.total_vector_count
    log.info("Loading dataset from %s ...", CSV_PATH)
    df = pd.read_csv(CSV_PATH)
    log.info("Loaded %d rows.", len(df))
    jobs = [clean_row(df.iloc[i]) for i in range(len(df))]
    external_jobs = fetch_configured_sources()
    if external_jobs:
        log.info("Loaded %d external listings from configured sources.", len(external_jobs))
        jobs.extend(external_jobs)
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


def _extract_experience_years(exp: str) -> tuple[int, int]:
    exp = _safe_str(exp)
    nums = [int(x) for x in re.findall(r"\d+", exp)]
    if len(nums) >= 2:
        return nums[0], nums[1]
    if len(nums) == 1:
        return nums[0], nums[0]
    return 0, 0


def compute_match_breakdown(profile: UserProfile, job: dict) -> dict:
    score_skills = 0
    score_experience = 0
    score_location = 0
    score_work_type = 0
    score_salary = 0

    profile_skills = {s.strip().lower() for s in profile.skills if s.strip()}
    job_skills = {s.strip().lower() for s in job.get("skills", []) if _safe_str(s)}
    if profile_skills and job_skills:
        overlap = profile_skills & job_skills
        ratio = len(overlap) / max(len(profile_skills), 1)
        score_skills = min(30, int(round(ratio * 30)))

    job_min, job_max = _extract_experience_years(job.get("experience", ""))
    if profile.experience <= 0 or (job_min == 0 and job_max == 0):
        score_experience = 10
    elif job_min <= profile.experience <= max(job_max, job_min):
        score_experience = 20
    elif abs(profile.experience - job_min) <= 1:
        score_experience = 14
    else:
        score_experience = 6

    profile_location = _safe_str(profile.location).lower()
    job_location = _safe_str(job.get("location", "")).lower()
    if not profile_location or not job_location:
        score_location = 10
    elif profile_location in job_location or job_location in profile_location:
        score_location = 20
    else:
        score_location = 5

    profile_work_type = _safe_str(profile.workType).lower()
    job_work_type = _safe_str(job.get("work_type", "")).lower()
    if not profile_work_type or profile_work_type == "any" or not job_work_type:
        score_work_type = 10
    elif profile_work_type in job_work_type:
        score_work_type = 15
    else:
        score_work_type = 4

    requested_salary = profile.salaryMin or 0
    job_salary_min = _extract_salary_min(_safe_str(job.get("salary", "")))
    if requested_salary <= 0 or job_salary_min <= 0:
        score_salary = 10
    elif job_salary_min >= requested_salary:
        score_salary = 15
    elif job_salary_min >= requested_salary * 0.9:
        score_salary = 10
    else:
        score_salary = 4

    total = score_skills + score_experience + score_location + score_work_type + score_salary
    confidence = "high" if total >= 75 else "medium" if total >= 55 else "low"
    return {
        "overall": total,
        "confidence": confidence,
        "components": {
            "skills": score_skills,
            "experience": score_experience,
            "location": score_location,
            "work_type": score_work_type,
            "salary": score_salary,
        },
    }

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


@app.post("/webhook", response_model=WebhookResponse, dependencies=[Depends(verify_api_key), Depends(verify_jwt)])
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
        return WebhookResponse(output="No matching jobs found. Please try different search terms.", sessionId=session_id)
    output = generate_response(query, candidates, history)

    top_matches = []
    for c in candidates[:TOP_N_RESULTS]:
        item = {
            "title": c.get("title", ""),
            "company": c.get("company", ""),
            "location": c.get("location", ""),
            "country": c.get("country", ""),
            "salary": c.get("salary", ""),
            "work_type": c.get("work_type", ""),
            "experience": c.get("experience", ""),
            "skills": c.get("skills", []),
            "score": c.get("score", 0),
        }
        if req.profile:
            item["score_breakdown"] = compute_match_breakdown(req.profile, c)
        top_matches.append(item)

    save_session_turn(session_id, query, output)
    log.info("[%s] /webhook done, session=%s", request_id, session_id)
    return WebhookResponse(output=output, sessionId=session_id, topMatches=top_matches)


@app.post("/index")
async def index_endpoint(force: bool = False, _: None = Depends(verify_api_key)):
    try:
        total = index_dataset(force=force)
        return {"status": "ok", "total_vectors": total}
    except Exception as e:
        log.exception("Indexing failed")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/parse-resume", dependencies=[Depends(verify_api_key), Depends(verify_jwt)])
async def parse_resume(file: UploadFile = File(...)):
    if not file.filename.endswith(".pdf"):
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

    # Keep a bounded raw text snapshot for downstream resume tailoring.
    parsed["resume_text"] = text[:6000]

    return parsed


@app.post("/resume-tailor", dependencies=[Depends(verify_api_key), Depends(verify_jwt)])
async def resume_tailor(req: ResumeTailorRequest):
    focus = ", ".join(req.focusAreas) if req.focusAreas else "summary, experience bullets, and ATS keywords"
    prompt = f"""You are an expert resume strategist.

Target role: {req.jobTitle} at {req.company}
Focus areas: {focus}

Candidate profile:
- Name: {req.profile.name}
- Desired role: {req.profile.desiredRole}
- Experience: {req.profile.experience} years
- Skills: {', '.join(req.profile.skills) if req.profile.skills else 'Not provided'}
- Education: {req.profile.education}

Job description:
{req.jobDescription[:1200] if req.jobDescription else 'Not provided'}

Current resume context:
{req.currentResumeText[:2000] if req.currentResumeText else 'Not provided'}

Return concise Markdown with these sections only:
## Professional Summary
## Experience Bullets (5)
## Skills To Highlight
## ATS Keywords To Include

Rules:
- Be specific to the target role
- Keep bullet language achievement-focused
- Do not include placeholders
"""

    response = get_openai().chat.completions.create(
        model=CHAT_MODEL,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.4,
        max_tokens=900,
    )
    return {"tailored_resume": response.choices[0].message.content.strip()}


@app.post("/cover-letter", dependencies=[Depends(verify_api_key), Depends(verify_jwt)])
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


@app.post("/interview-prep", dependencies=[Depends(verify_api_key), Depends(verify_jwt)])
async def interview_prep(req: InterviewPrepRequest):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM applications WHERE id = ?", (req.application_id,)) as cursor:
            row = await cursor.fetchone()

    if not row:
        raise HTTPException(status_code=404, detail="Application not found")

    app_item = dict(row)
    stage = _safe_str(app_item.get("status", "saved")) or "saved"
    profile_summary = "No profile supplied"
    if req.profile:
        profile_summary = (
            f"Desired role: {req.profile.desiredRole}\n"
            f"Experience: {req.profile.experience} years\n"
            f"Skills: {', '.join(req.profile.skills) if req.profile.skills else 'Not provided'}"
        )

    prompt = f"""You are an interview coach. Build a prep brief aligned to the current application stage.

Application:
- Role: {app_item.get('job_title', '')}
- Company: {app_item.get('company', '')}
- Location: {app_item.get('location', '')}
- Stage: {stage}

Candidate profile:
{profile_summary}

User focus: {req.focus or 'General preparation'}

Return Markdown with exactly these sections:
## Stage Strategy
## Likely Questions (8)
## Strong Talking Points
## 24-Hour Action Plan

Make advice practical and stage-specific.
"""

    response = get_openai().chat.completions.create(
        model=CHAT_MODEL,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.4,
        max_tokens=950,
    )

    return {
        "application_id": req.application_id,
        "stage": stage,
        "prep": response.choices[0].message.content.strip(),
    }


@app.post("/bookmark", dependencies=[Depends(verify_api_key), Depends(verify_jwt)])
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


@app.get("/bookmarks/{session_id}", dependencies=[Depends(verify_api_key), Depends(verify_jwt)])
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
        item["job_data"] = json.loads(item.get("job_data", "{}") or "{}")
        result.append(item)
    return {"bookmarks": result}


@app.post("/feedback", dependencies=[Depends(verify_api_key), Depends(verify_jwt)])
async def submit_feedback(req: FeedbackRequest):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """INSERT INTO feedback (session_id, job_title, company, rating, comment, created_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (req.session_id, req.job_title, req.company, req.rating, req.comment, datetime.utcnow().isoformat())
        )
        await db.commit()
    return {"status": "ok"}


@app.post("/applications", dependencies=[Depends(verify_api_key), Depends(verify_jwt)])
async def create_application(req: ApplicationCreateRequest):
    now = datetime.utcnow().isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """INSERT INTO applications (
                session_id, job_title, company, status, notes, location, salary, source,
                applied_at, updated_at, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                req.session_id,
                req.job_title,
                req.company,
                "saved",
                req.notes,
                req.location,
                req.salary,
                req.source,
                None,
                now,
                now,
            ),
        )
        await db.commit()
        async with db.execute("SELECT last_insert_rowid()") as cursor:
            row = await cursor.fetchone()
    return {"status": "saved", "application_id": row[0] if row else None}


@app.get("/applications/{session_id}", dependencies=[Depends(verify_api_key), Depends(verify_jwt)])
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


@app.patch("/applications/{application_id}", dependencies=[Depends(verify_api_key), Depends(verify_jwt)])
async def update_application(application_id: int, req: ApplicationUpdateRequest):
    if req.status is None and req.notes is None:
        raise HTTPException(status_code=400, detail="Provide at least one field to update")

    allowed_status = {"saved", "applied", "oa", "interview", "offer", "rejected"}
    if req.status is not None and req.status not in allowed_status:
        raise HTTPException(status_code=400, detail=f"Invalid status. Allowed: {', '.join(sorted(allowed_status))}")

    updates = []
    params = []

    if req.status is not None:
        updates.append("status = ?")
        params.append(req.status)
        if req.status == "applied":
            updates.append("applied_at = COALESCE(applied_at, ?)")
            params.append(datetime.utcnow().isoformat())

    if req.notes is not None:
        updates.append("notes = ?")
        params.append(req.notes)

    updates.append("updated_at = ?")
    params.append(datetime.utcnow().isoformat())
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


@app.post("/alerts/subscribe", dependencies=[Depends(verify_api_key), Depends(verify_jwt)])
async def subscribe_alerts(req: AlertSubscriptionRequest):
    frequency = req.frequency.lower().strip()
    if frequency not in {"daily", "weekly"}:
        raise HTTPException(status_code=400, detail="frequency must be daily or weekly")
    now = datetime.utcnow().isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """INSERT INTO alert_subscriptions (email, name, profile_json, frequency, active, created_at)
               VALUES (?, ?, ?, ?, 1, ?)
               ON CONFLICT(email) DO UPDATE SET
                 name = excluded.name,
                 profile_json = excluded.profile_json,
                 frequency = excluded.frequency,
                 active = 1""",
            (req.email.strip().lower(), req.name, req.profile.model_dump_json(), frequency, now),
        )
        await db.commit()
    await _send_confirmation_email(
        req.email.strip().lower(),
        req.name or req.email.strip().split("@")[0],
        f"Your {frequency} alert subscription is active and you will receive new matching jobs by email.",
        "JobMatch AI alerts confirmed",
    )
    return {"status": "subscribed", "email": req.email.strip().lower(), "frequency": frequency}


@app.get("/alerts/subscriptions/{email}", dependencies=[Depends(verify_api_key), Depends(verify_jwt)])
async def get_alert_subscription(email: str):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM alert_subscriptions WHERE email = ?",
            (email.strip().lower(),),
        ) as cursor:
            row = await cursor.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Subscription not found")

    item = dict(row)
    try:
        item["profile"] = json.loads(item.get("profile_json") or "{}")
    except Exception:
        item["profile"] = {}
    return item


@app.patch("/alerts/subscriptions/{email}", dependencies=[Depends(verify_api_key), Depends(verify_jwt)])
async def update_alert_subscription(email: str, req: AlertSubscriptionUpdateRequest):
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "UPDATE alert_subscriptions SET active = ? WHERE email = ?",
            (1 if req.active else 0, email.strip().lower()),
        )
        await db.commit()
    if cursor.rowcount == 0:
        raise HTTPException(status_code=404, detail="Subscription not found")
    return {"status": "updated", "active": req.active}


@app.post("/alerts/run", dependencies=[Depends(verify_api_key), Depends(verify_jwt)])
async def run_alerts(req: AlertRunRequest):
    frequency = req.frequency.lower().strip()
    if frequency not in {"auto", "daily", "weekly"}:
        raise HTTPException(status_code=400, detail="frequency must be auto, daily, or weekly")
    result = await run_alert_digests(frequency)
    return result


@app.post("/auth/google", dependencies=[Depends(verify_api_key)])
async def auth_google(req: GoogleAuthRequest):
    payload = await asyncio.to_thread(_verify_google_id_token_sync, req.credential)
    email = _safe_str(payload.get("email", "")).lower()
    name = _safe_str(payload.get("name", "")) or email.split("@")[0]
    picture = _safe_str(payload.get("picture", ""))
    google_sub = _safe_str(payload.get("sub", ""))

    profile = req.profile or UserProfile(email=email, name=name)
    user = await _upsert_user_profile(
        email=email,
        name=name,
        google_sub=google_sub,
        picture=picture,
        profile=profile,
        send_confirmation=True,
    )

    access_token = _create_jwt(email, name, picture)
    return {
        "status": "ok",
        "user": user,
        "profile": profile.model_dump(),
        "email_verified": True,
        "access_token": access_token,
        "token_type": "bearer",
    }


@app.post("/profile", dependencies=[Depends(verify_api_key), Depends(verify_jwt)])
async def save_profile(req: ProfileUpsertRequest):
    user = await _upsert_user_profile(
        email=req.email,
        name=req.name,
        google_sub=req.google_sub,
        picture=req.picture,
        profile=req.profile,
        send_confirmation=req.send_confirmation,
    )
    return {"status": "saved", "user": user}


@app.get("/profile/{email}", dependencies=[Depends(verify_api_key), Depends(verify_jwt)])
async def get_profile(email: str):
    normalized_email = _safe_str(email).lower()
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM users WHERE email = ?",
            (normalized_email,),
        ) as cursor:
            row = await cursor.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Profile not found")

    item = dict(row)
    try:
        item["profile"] = json.loads(item.get("profile_json") or "{}")
    except Exception:
        item["profile"] = {}
    return item


@app.post("/score-breakdown", dependencies=[Depends(verify_api_key), Depends(verify_jwt)])
async def score_breakdown(req: ScoreBreakdownRequest):
    return {"score_breakdown": compute_match_breakdown(req.profile, req.job)}


@app.post("/send-results", dependencies=[Depends(verify_api_key), Depends(verify_jwt)])
async def send_results(req: SendResultsRequest):
    if not RESEND_API_KEY:
        raise HTTPException(status_code=503, detail="Email service not configured")
    if not _RESEND_AVAILABLE or resend_lib is None:
        raise HTTPException(status_code=503, detail="Email service library is not installed on this server")
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
