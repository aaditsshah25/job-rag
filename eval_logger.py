"""
eval_logger.py — writes one JSONL record per pipeline run to eval_log.jsonl
Call log_eval_record() from the /webhook handler after generate_response() returns.
"""
import json
import time
import os
from typing import Optional

EVAL_LOG_PATH = os.path.join(os.path.dirname(__file__), "eval_log.jsonl")


def _slim_candidate(c: dict) -> dict:
    return {
        "title": c.get("title", ""),
        "company": c.get("company", ""),
        "score": c.get("score", 0),
        "skills": c.get("skills", []),
        "location": c.get("location", ""),
        "work_type": c.get("work_type", ""),
        "salary": c.get("salary", ""),
    }


def log_eval_record(
    *,
    profile: Optional[object],
    query: str,
    candidates_before_rerank: list,
    candidates_after_rerank: list,
    llm_output: str,
    retrieval_latency_ms: float,
    generation_latency_ms: float,
) -> None:
    profile_dict = {}
    if profile is not None:
        try:
            profile_dict = {
                "skills": getattr(profile, "skills", []),
                "desiredRole": getattr(profile, "desiredRole", ""),
                "location": getattr(profile, "location", ""),
                "workType": getattr(profile, "workType", "Any"),
                "experience": getattr(profile, "experience", 0),
                "salaryMin": getattr(profile, "salaryMin", None),
                "industry": getattr(profile, "industry", ""),
                "education": getattr(profile, "education", ""),
            }
        except Exception:
            pass

    record = {
        "timestamp": time.time(),
        "profile": profile_dict,
        "query": query,
        "candidates_before_rerank": [_slim_candidate(c) for c in candidates_before_rerank],
        "candidates_after_rerank": [_slim_candidate(c) for c in candidates_after_rerank],
        "llm_output": llm_output,
        "retrieval_latency_ms": round(retrieval_latency_ms, 2),
        "generation_latency_ms": round(generation_latency_ms, 2),
    }

    try:
        with open(EVAL_LOG_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(record) + "\n")
    except Exception as exc:
        import logging
        logging.getLogger(__name__).warning("eval_logger: failed to write record: %s", exc)
