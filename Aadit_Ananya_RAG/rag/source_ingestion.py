"""
External source ingestion utilities for JobMatch AI.

Each external listing is normalized into one document using the same schema
as clean_row() in backend.py so it can be embedded and indexed directly.
"""

from __future__ import annotations

import hashlib
import json
import os
import logging
from typing import Any
from urllib.parse import quote
from urllib.request import Request, urlopen

log = logging.getLogger(__name__)


def _safe_str(val: Any) -> str:
    if val is None:
        return ""
    return str(val).strip()


def _to_salary_text(min_val: Any, max_val: Any, suffix: str = "/yr") -> str:
    try:
        lo = int(float(min_val)) if min_val not in (None, "") else None
        hi = int(float(max_val)) if max_val not in (None, "") else None
    except Exception:
        return ""
    if lo is not None and hi is not None:
        return f"${lo:,} - ${hi:,}{suffix}"
    if lo is not None:
        return f"${lo:,}{suffix}"
    if hi is not None:
        return f"${hi:,}{suffix}"
    return ""


def _join_list(values: list[Any]) -> str:
    return ", ".join(_safe_str(v) for v in values if _safe_str(v))


def _normalize_record(source: str, raw: dict[str, Any]) -> dict[str, Any]:
    """
    Normalize one listing into backend-compatible job schema.
    """
    return {
        "job_id": _safe_str(raw.get("job_id")) or hashlib.md5(
            f"{source}|{raw.get('title','')}|{raw.get('company','')}|{raw.get('external_url','')}".encode("utf-8")
        ).hexdigest()[:16],
        "title": _safe_str(raw.get("title")),
        "role": _safe_str(raw.get("role")) or _safe_str(raw.get("title")),
        "company": _safe_str(raw.get("company")),
        "location": _safe_str(raw.get("location")),
        "country": _safe_str(raw.get("country")),
        "work_type": _safe_str(raw.get("work_type")),
        "company_size": _safe_str(raw.get("company_size")),
        "experience": _safe_str(raw.get("experience")),
        "qualifications": _safe_str(raw.get("qualifications")),
        "salary": _safe_str(raw.get("salary")),
        "description": _safe_str(raw.get("description")),
        "responsibilities": _safe_str(raw.get("responsibilities")),
        "skills": raw.get("skills") or [],
        "benefits": raw.get("benefits") or [],
        "sector": _safe_str(raw.get("sector")),
        "industry": _safe_str(raw.get("industry")),
        "posting_date": _safe_str(raw.get("posting_date")),
        "portal": _safe_str(raw.get("portal")) or source,
        "source": source,
        "external_url": _safe_str(raw.get("external_url")),
    }


def _get_json(url: str, headers: dict[str, str] | None = None) -> Any:
    req = Request(url, headers=headers or {"User-Agent": "jobmatch-ai/2.0"})
    with urlopen(req, timeout=30) as resp:  # nosec B310
        return json.loads(resp.read().decode("utf-8"))


def _post_json(url: str, payload: dict[str, Any], headers: dict[str, str] | None = None) -> Any:
    body = json.dumps(payload).encode("utf-8")
    merged_headers = {"Content-Type": "application/json", "User-Agent": "jobmatch-ai/2.0"}
    if headers:
        merged_headers.update(headers)
    req = Request(url, data=body, headers=merged_headers, method="POST")
    with urlopen(req, timeout=30) as resp:  # nosec B310
        return json.loads(resp.read().decode("utf-8"))


def fetch_usajobs(max_items: int = 150) -> list[dict[str, Any]]:
    api_key = os.getenv("USAJOBS_API_KEY", "")
    api_email = os.getenv("USAJOBS_API_EMAIL", "")
    if not api_key or not api_email:
        return []

    url = (
        "https://data.usajobs.gov/api/search?"
        f"ResultsPerPage={max(1, min(max_items, 500))}&Page=1"
    )
    payload = _get_json(
        url,
        headers={
            "Host": "data.usajobs.gov",
            "User-Agent": api_email,
            "Authorization-Key": api_key,
        },
    )
    items = payload.get("SearchResult", {}).get("SearchResultItems", [])
    out: list[dict[str, Any]] = []
    for item in items:
        d = item.get("MatchedObjectDescriptor", {})
        ua = d.get("UserArea", {}).get("Details", {}) or {}
        loc = ""
        if d.get("PositionLocation"):
            first_loc = d.get("PositionLocation")[0]
            loc = _safe_str(first_loc.get("LocationName"))
        salary = ""
        rem = d.get("PositionRemuneration") or []
        if rem:
            salary = _to_salary_text(rem[0].get("MinimumRange"), rem[0].get("MaximumRange"))
        out.append(
            _normalize_record(
                "usajobs",
                {
                    "job_id": d.get("PositionID") or item.get("MatchedObjectId"),
                    "title": d.get("PositionTitle"),
                    "company": d.get("OrganizationName"),
                    "location": loc,
                    "country": "USA",
                    "work_type": _join_list([x.get("Name") for x in (d.get("PositionSchedule") or [])]),
                    "experience": _safe_str(ua.get("LowGrade")) + ("-" + _safe_str(ua.get("HighGrade")) if ua.get("HighGrade") else ""),
                    "qualifications": ua.get("QualificationSummary") or ua.get("Education"),
                    "salary": salary,
                    "description": ua.get("JobSummary") or "",
                    "responsibilities": ua.get("MajorDuties") or "",
                    "benefits": [ua.get("Benefits")] if ua.get("Benefits") else [],
                    "industry": d.get("DepartmentName"),
                    "posting_date": d.get("PublicationStartDate"),
                    "portal": "USAJOBS",
                    "external_url": (d.get("PositionURI") or ""),
                },
            )
        )
    return out


def fetch_adzuna(max_items: int = 100) -> list[dict[str, Any]]:
    app_id = os.getenv("ADZUNA_APP_ID", "")
    app_key = os.getenv("ADZUNA_APP_KEY", "")
    country = os.getenv("ADZUNA_COUNTRY", "us")
    if not app_id or not app_key:
        return []

    results_per_page = max(1, min(max_items, 50))
    what = quote(os.getenv("ADZUNA_WHAT", "software engineer"))
    where = quote(os.getenv("ADZUNA_WHERE", "united states"))
    url = (
        f"https://api.adzuna.com/v1/api/jobs/{country}/search/1"
        f"?app_id={app_id}&app_key={app_key}&results_per_page={results_per_page}"
        f"&what={what}&where={where}&content-type=application/json"
    )
    payload = _get_json(url)
    out: list[dict[str, Any]] = []
    for job in payload.get("results", []):
        out.append(
            _normalize_record(
                "adzuna",
                {
                    "job_id": job.get("id"),
                    "title": job.get("title"),
                    "company": (job.get("company") or {}).get("display_name"),
                    "location": (job.get("location") or {}).get("display_name"),
                    "country": country.upper(),
                    "work_type": "",
                    "salary": _to_salary_text(job.get("salary_min"), job.get("salary_max")),
                    "description": job.get("description"),
                    "skills": [],
                    "industry": (job.get("category") or {}).get("label"),
                    "posting_date": job.get("created"),
                    "portal": "Adzuna",
                    "external_url": job.get("redirect_url"),
                },
            )
        )
    return out


def fetch_remotive(max_items: int = 120) -> list[dict[str, Any]]:
    payload = _get_json("https://remotive.com/api/remote-jobs")
    out: list[dict[str, Any]] = []
    for job in payload.get("jobs", [])[:max_items]:
        out.append(
            _normalize_record(
                "remotive",
                {
                    "job_id": job.get("id"),
                    "title": job.get("title"),
                    "company": job.get("company_name"),
                    "location": job.get("candidate_required_location"),
                    "country": "Remote",
                    "work_type": "Remote",
                    "salary": job.get("salary") or "",
                    "description": job.get("description"),
                    "skills": job.get("tags") or [],
                    "industry": job.get("category"),
                    "posting_date": job.get("publication_date"),
                    "portal": "Remotive",
                    "external_url": job.get("url"),
                },
            )
        )
    return out


def fetch_arbeitnow(max_items: int = 120) -> list[dict[str, Any]]:
    payload = _get_json("https://www.arbeitnow.com/api/job-board-api")
    out: list[dict[str, Any]] = []
    for job in payload.get("data", [])[:max_items]:
        out.append(
            _normalize_record(
                "arbeitnow",
                {
                    "job_id": job.get("slug") or job.get("title"),
                    "title": job.get("title"),
                    "company": job.get("company_name"),
                    "location": job.get("location"),
                    "country": "EU",
                    "work_type": "Remote" if bool(job.get("remote")) else "",
                    "description": job.get("description"),
                    "skills": job.get("tags") or [],
                    "benefits": job.get("benefits") or [],
                    "posting_date": job.get("created_at"),
                    "portal": "Arbeitnow",
                    "external_url": job.get("url"),
                },
            )
        )
    return out


def fetch_jooble(max_items: int = 100) -> list[dict[str, Any]]:
    api_key = os.getenv("JOOBLE_API_KEY", "")
    if not api_key:
        return []
    page = int(os.getenv("JOOBLE_PAGE", "1"))
    keywords = os.getenv("JOOBLE_KEYWORDS", "software engineer")
    location = os.getenv("JOOBLE_LOCATION", "United States")
    payload = _post_json(
        f"https://jooble.org/api/{api_key}",
        {
            "keywords": keywords,
            "location": location,
            "page": str(max(1, page)),
        },
    )
    out: list[dict[str, Any]] = []
    for job in payload.get("jobs", [])[:max_items]:
        out.append(
            _normalize_record(
                "jooble",
                {
                    "job_id": job.get("id"),
                    "title": job.get("title"),
                    "company": job.get("company"),
                    "location": job.get("location"),
                    "country": "",
                    "work_type": job.get("type"),
                    "salary": job.get("salary"),
                    "description": job.get("snippet"),
                    "posting_date": job.get("updated"),
                    "portal": "Jooble",
                    "external_url": job.get("link"),
                },
            )
        )
    return out


def fetch_greenhouse(max_items_per_board: int = 100) -> list[dict[str, Any]]:
    board_tokens = [
        t.strip() for t in os.getenv("GREENHOUSE_BOARD_TOKENS", "").split(",") if t.strip()
    ]
    if not board_tokens:
        return []
    out: list[dict[str, Any]] = []
    for token in board_tokens:
        payload = _get_json(f"https://boards-api.greenhouse.io/v1/boards/{token}/jobs")
        for job in payload.get("jobs", [])[:max_items_per_board]:
            out.append(
                _normalize_record(
                    "greenhouse",
                    {
                        "job_id": job.get("id"),
                        "title": job.get("title"),
                        "company": token,
                        "location": (job.get("location") or {}).get("name"),
                        "country": "",
                        "work_type": "",
                        "description": _safe_str(job.get("content")),
                        "posting_date": job.get("updated_at") or job.get("absolute_url"),
                        "portal": "Greenhouse",
                        "external_url": job.get("absolute_url"),
                    },
                )
            )
    return out


def fetch_lever(max_items_per_site: int = 100) -> list[dict[str, Any]]:
    site_names = [t.strip() for t in os.getenv("LEVER_SITE_NAMES", "").split(",") if t.strip()]
    if not site_names:
        return []
    out: list[dict[str, Any]] = []
    for site in site_names:
        payload = _get_json(f"https://api.lever.co/v0/postings/{site}?mode=json")
        for job in payload[:max_items_per_site]:
            categories = job.get("categories") or {}
            out.append(
                _normalize_record(
                    "lever",
                    {
                        "job_id": job.get("id"),
                        "title": job.get("text"),
                        "company": site,
                        "location": categories.get("location"),
                        "country": "",
                        "work_type": categories.get("commitment"),
                        "description": _safe_str(job.get("descriptionPlain") or job.get("description")),
                        "responsibilities": _safe_str(job.get("lists"))[:1000],
                        "skills": [],
                        "posting_date": job.get("createdAt"),
                        "portal": "Lever",
                        "external_url": job.get("hostedUrl"),
                    },
                )
            )
    return out


def fetch_configured_sources() -> list[dict[str, Any]]:
    """
    Fetches enabled external sources.
    Default behavior is safe: disabled unless ENABLE_EXTERNAL_SOURCES=true.
    """
    if os.getenv("ENABLE_EXTERNAL_SOURCES", "").lower() not in {"1", "true", "yes"}:
        return []

    combined: list[dict[str, Any]] = []
    fetchers = [
        fetch_usajobs,
        fetch_adzuna,
        fetch_remotive,
        fetch_arbeitnow,
        fetch_jooble,
        fetch_greenhouse,
        fetch_lever,
    ]
    for fetcher in fetchers:
        try:
            combined.extend(fetcher())
        except Exception as exc:
            # Keep indexing resilient if one source fails, but emit a warning for debugging.
            log.warning("External source fetch failed for %s: %s", fetcher.__name__, exc)
            continue
    return combined
