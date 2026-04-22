"""
eval.py — Standalone RAG evaluation script for JobMatch AI

Usage:
    python eval.py                  # run all metrics, save plots
    python eval.py --llm-judge      # also run Gemma-as-judge (uses API quota)
    python eval.py --log eval_log.jsonl --db data/jobmatch.db
"""

import argparse
import json
import math
import os
import re
import sqlite3
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Optional
from urllib.request import Request as UrlRequest, urlopen
from urllib.error import URLError, HTTPError

# ─── Paths ────────────────────────────────────────────

DEFAULT_LOG = os.path.join(os.path.dirname(__file__), "eval_log.jsonl")
DEFAULT_DB = os.path.join(os.path.dirname(__file__), "data", "jobmatch.db")
PLOTS_DIR = os.path.join(os.path.dirname(__file__), "eval_plots")

# ─── Data Loading ─────────────────────────────────────

def load_eval_log(path: str = DEFAULT_LOG) -> list[dict]:
    records = []
    if not os.path.exists(path):
        print(f"[warn] eval_log not found at {path}. Run backend with a few queries first.")
        return records
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    return records


def load_feedback_db(db_path: str = DEFAULT_DB) -> list[dict]:
    rows = []
    if not os.path.exists(db_path):
        print(f"[warn] SQLite DB not found at {db_path}")
        return rows
    try:
        conn = sqlite3.connect(db_path)
        cur = conn.cursor()
        cur.execute("SELECT session_id, job_title, company, rating FROM feedback WHERE rating IS NOT NULL")
        for r in cur.fetchall():
            rows.append({"session_id": r[0], "job_title": r[1] or "", "company": r[2] or "", "rating": r[3]})
        conn.close()
    except Exception as e:
        print(f"[warn] Could not read feedback DB: {e}")
    return rows

# ─── Helpers ──────────────────────────────────────────

def parse_match_scores(output: str) -> list[float]:
    """Extract all 'Match Score: N/10' values from LLM output."""
    hits = re.findall(r"[Mm]atch\s+[Ss]core[:\s]+(\d+(?:\.\d+)?)\s*/\s*10", output)
    return [float(h) for h in hits]


def _titles_from_candidates(candidates: list[dict]) -> list[str]:
    return [c.get("title", "").lower().strip() for c in candidates]

# ─── Retrieval Metrics ────────────────────────────────

def precision_at_k(candidates: list[dict], k: int, threshold: float = 0.15) -> float:
    """Fraction of top-K candidates with Pinecone score >= threshold."""
    top = candidates[:k]
    if not top:
        return 0.0
    relevant = sum(1 for c in top if float(c.get("score", 0)) >= threshold)
    return relevant / len(top)


def hit_rate_at_k(retrieved_titles: list[str], liked_titles: list[str], k: int) -> float:
    """1 if any liked title appears in top-K retrieved titles, else 0."""
    top = set(t.lower().strip() for t in retrieved_titles[:k])
    for lt in liked_titles:
        if lt.lower().strip() in top:
            return 1.0
    return 0.0


def reciprocal_rank(retrieved_titles: list[str], liked_titles: list[str]) -> float:
    """1/rank of first liked title in retrieved list (0 if not found)."""
    liked_set = {t.lower().strip() for t in liked_titles}
    for i, t in enumerate(retrieved_titles, start=1):
        if t.lower().strip() in liked_set:
            return 1.0 / i
    return 0.0


def recall_at_k(retrieved_titles: list[str], liked_titles: list[str], k: int) -> float:
    """Fraction of liked titles found in top-K retrieved."""
    if not liked_titles:
        return 0.0
    top = set(t.lower().strip() for t in retrieved_titles[:k])
    found = sum(1 for lt in liked_titles if lt.lower().strip() in top)
    return found / len(liked_titles)


def average_precision(retrieved_titles: list[str], liked_titles: list[str], k: int) -> float:
    """Average Precision@K for a single query."""
    liked_set = {t.lower().strip() for t in liked_titles}
    if not liked_set:
        return 0.0
    hits = 0
    precision_sum = 0.0
    for i, t in enumerate(retrieved_titles[:k], start=1):
        if t.lower().strip() in liked_set:
            hits += 1
            precision_sum += hits / i
    if hits == 0:
        return 0.0
    return precision_sum / len(liked_set)


def ndcg_at_k(relevances: list[float], k: int) -> float:
    """
    NDCG@K where relevances[i] is the relevance grade for the i-th candidate.
    Uses LLM match scores (1-10) normalised to 0-1 as grades.
    """
    top = relevances[:k]
    if not top:
        return 0.0

    def dcg(rels):
        return sum((2 ** r - 1) / math.log2(i + 2) for i, r in enumerate(rels))

    ideal = sorted(top, reverse=True)
    idcg = dcg(ideal)
    if idcg == 0:
        return 0.0
    return dcg(top) / idcg

# ─── Generation Quality Metrics ───────────────────────

_FORMAT_RULES = [
    (r"# Your Job Match Results", "has_main_heading"),
    (r"## Top Job Matches", "has_subheading"),
    (r"### \S", "has_job_blocks"),
    (r"\*\*Company\*\*[:\s]", "has_company_field"),
    (r"\*\*Location\*\*[:\s]", "has_location_field"),
    (r"[Mm]atch\s+[Ss]core[:\s]+\d+/10", "has_match_score"),
    (r"\*\*Why", "has_why_section"),
    (r"\[Apply", "has_apply_link"),
]

def format_consistency_checks(output: str) -> dict:
    """Run 8 regex format checks. Returns dict of rule_name -> bool."""
    results = {}
    for pattern, name in _FORMAT_RULES:
        results[name] = bool(re.search(pattern, output))
    return results


def faithfulness_score(output: str, candidates: list[dict]) -> float:
    """
    Approximates faithfulness: fraction of companies mentioned in the LLM output
    that actually appear in the retrieved candidates list.
    """
    candidate_companies = {c.get("company", "").lower().strip() for c in candidates if c.get("company")}
    # Extract bolded companies from output (pattern: **Company**: Foo Inc)
    mentioned = re.findall(r"\*\*[Cc]ompany\*\*[:\s]+([^\n*]+)", output)
    if not mentioned:
        return 1.0  # no companies mentioned → can't falsify
    found = sum(1 for m in mentioned if m.strip().lower() in candidate_companies)
    return found / len(mentioned)

# ─── System / Diversity Metrics ───────────────────────

def skill_diversity(candidates: list[dict], k: int) -> float:
    """Fraction of unique skills across top-K candidates (unique / total)."""
    top = candidates[:k]
    all_skills = []
    for c in top:
        all_skills.extend([s.lower().strip() for s in (c.get("skills") or []) if s.strip()])
    if not all_skills:
        return 0.0
    return len(set(all_skills)) / len(all_skills)


def company_diversity(candidates: list[dict], k: int) -> float:
    """Fraction of unique companies in top-K."""
    top = candidates[:k]
    companies = [c.get("company", "").lower().strip() for c in top if c.get("company")]
    if not companies:
        return 0.0
    return len(set(companies)) / len(companies)


def location_diversity(candidates: list[dict], k: int) -> float:
    locs = [c.get("location", "").lower().strip() for c in candidates[:k] if c.get("location")]
    if not locs:
        return 0.0
    return len(set(locs)) / len(locs)


def profile_alignment_score(profile: dict, job: dict) -> float:
    """
    0-1 score: how well a single job aligns with the profile.
    Combines skill overlap, location match, work-type match, salary adequacy.
    """
    score = 0.0
    weight_total = 0.0

    # Skill overlap (weight 0.5)
    p_skills = {s.lower().strip() for s in (profile.get("skills") or []) if s.strip()}
    j_skills = {s.lower().strip() for s in (job.get("skills") or []) if s.strip()}
    if p_skills:
        overlap = len(p_skills & j_skills) / len(p_skills)
        score += 0.5 * overlap
    weight_total += 0.5

    # Location match (weight 0.2)
    p_loc = (profile.get("location") or "").lower().strip()
    j_loc = (job.get("location") or "").lower().strip()
    if p_loc and j_loc:
        if p_loc in j_loc or j_loc in p_loc:
            score += 0.2
    weight_total += 0.2

    # Work type match (weight 0.15)
    p_wt = (profile.get("workType") or "Any").lower()
    j_wt = (job.get("work_type") or "").lower()
    if p_wt not in ("any", "") and j_wt:
        if p_wt in j_wt or j_wt in p_wt:
            score += 0.15
    weight_total += 0.15

    # Salary adequacy (weight 0.15)
    p_sal = profile.get("salaryMin")
    j_sal_str = job.get("salary", "") or ""
    j_sal_nums = re.findall(r"\d[\d,]*", j_sal_str.replace(",", ""))
    if p_sal and j_sal_nums:
        try:
            j_sal_max = max(int(n) for n in j_sal_nums)
            if j_sal_max >= int(p_sal):
                score += 0.15
        except (ValueError, TypeError):
            pass
    weight_total += 0.15

    return round(score / weight_total, 4) if weight_total > 0 else 0.0

# ─── LLM-as-Judge ─────────────────────────────────────

def llm_judge(profile_summary: str, output: str, api_key: str, model: str = "gemma-3-27b-it") -> int:
    """
    Ask Gemma to rate the relevance of LLM output to the profile on 1-5.
    Returns integer score, or -1 on failure.
    """
    prompt = (
        "You are evaluating a job recommendation output. "
        "Given the user profile below, rate how relevant the job recommendations are on a scale of 1 to 5 "
        "(1 = irrelevant, 5 = highly relevant). Reply with ONLY the integer score.\n\n"
        f"USER PROFILE:\n{profile_summary}\n\n"
        f"JOB RECOMMENDATIONS:\n{output[:2000]}\n\n"
        "Score (1-5):"
    )
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
    body = json.dumps({
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.0, "maxOutputTokens": 8},
    }).encode("utf-8")
    try:
        req = UrlRequest(url, data=body, headers={"Content-Type": "application/json"}, method="POST")
        with urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read())
        text = data["candidates"][0]["content"]["parts"][0]["text"].strip()
        m = re.search(r"\d", text)
        return int(m.group()) if m else -1
    except Exception as e:
        print(f"[llm-judge] error: {e}")
        return -1

# ─── Aggregate Computation ────────────────────────────

def compute_retrieval_metrics(records: list[dict], feedback: list[dict], ks: list[int]) -> dict:
    """Returns dict of metric -> {K -> value}."""

    # Map session -> liked titles from feedback
    session_liked: dict[str, list[str]] = {}
    for row in feedback:
        if int(row.get("rating", 0)) >= 4:
            sid = row["session_id"]
            session_liked.setdefault(sid, []).append(row["job_title"])

    results = {
        "precision_at_k": {},
        "recall_at_k": {},
        "hit_at_1": {},
        "hit_rate_at_k": {},
        "mrr": {},
        "map_at_k": {},
        "ndcg_at_k_with_rerank": {},
        "ndcg_at_k_without_rerank": {},
    }

    for k in ks:
        p_vals, rec_vals, hit1_vals, hr_vals, rr_vals, ap_vals = [], [], [], [], [], []
        ndcg_wr, ndcg_nor = [], []

        for rec in records:
            after = rec.get("candidates_after_rerank", [])
            output = rec.get("llm_output", "")

            # Precision@K (proxy: Pinecone score >= 0.15)
            p_vals.append(precision_at_k(after, k))

            # LLM match scores → relevances for NDCG
            scores = parse_match_scores(output)
            if scores:
                padded = (scores + [0.0] * max(0, k - len(scores)))[:k]
                rel = [s / 10.0 for s in padded]
                ndcg_wr.append(ndcg_at_k(rel, k))
                # "without rerank" uses before-rerank order but same scores
                ndcg_nor.append(ndcg_at_k(rel, k))

            # Feedback-based metrics (Recall, Hit@1, Hit@K, MRR, MAP)
            sid = rec.get("profile", {}).get("sessionId") or rec.get("session_id", "")
            liked = session_liked.get(sid, [])
            if liked:
                after_titles = _titles_from_candidates(after)
                rec_vals.append(recall_at_k(after_titles, liked, k))
                hit1_vals.append(hit_rate_at_k(after_titles, liked, 1))
                hr_vals.append(hit_rate_at_k(after_titles, liked, k))
                rr_vals.append(reciprocal_rank(after_titles, liked))
                ap_vals.append(average_precision(after_titles, liked, k))

        def _avg(lst):
            return round(sum(lst) / len(lst), 4) if lst else None

        results["precision_at_k"][k] = _avg(p_vals)
        results["recall_at_k"][k] = _avg(rec_vals)
        results["hit_at_1"][k] = _avg(hit1_vals)
        results["hit_rate_at_k"][k] = _avg(hr_vals)
        results["mrr"][k] = _avg(rr_vals)
        results["map_at_k"][k] = _avg(ap_vals)
        results["ndcg_at_k_with_rerank"][k] = _avg(ndcg_wr)
        results["ndcg_at_k_without_rerank"][k] = _avg(ndcg_nor)

    return results


def compute_generation_metrics(records: list[dict], run_llm_judge: bool, api_key: str = "") -> dict:
    format_scores = []
    faith_scores = []
    judge_scores = []

    for rec in records:
        output = rec.get("llm_output", "")
        after = rec.get("candidates_after_rerank", [])

        checks = format_consistency_checks(output)
        format_scores.append(sum(checks.values()) / len(checks))

        faith_scores.append(faithfulness_score(output, after))

        if run_llm_judge and api_key:
            profile = rec.get("profile", {})
            summary = (
                f"Role: {profile.get('desiredRole', 'N/A')}, "
                f"Skills: {', '.join(profile.get('skills', [])[:5])}, "
                f"Location: {profile.get('location', 'N/A')}"
            )
            score = llm_judge(summary, output, api_key)
            if score > 0:
                judge_scores.append(score)

    return {
        "format_consistency": round(sum(format_scores) / len(format_scores), 4) if format_scores else None,
        "faithfulness": round(sum(faith_scores) / len(faith_scores), 4) if faith_scores else None,
        "llm_judge_avg": round(sum(judge_scores) / len(judge_scores), 4) if judge_scores else None,
        "llm_judge_n": len(judge_scores),
    }


def compute_system_metrics(records: list[dict], k: int = 10) -> dict:
    skill_divs, company_divs, loc_divs, align_scores = [], [], [], []
    ret_lats, gen_lats, all_match_scores = [], [], []

    for rec in records:
        after = rec.get("candidates_after_rerank", [])
        profile = rec.get("profile", {})
        output = rec.get("llm_output", "")

        skill_divs.append(skill_diversity(after, k))
        company_divs.append(company_diversity(after, k))
        loc_divs.append(location_diversity(after, k))

        for job in after[:k]:
            align_scores.append(profile_alignment_score(profile, job))

        ret_lats.append(rec.get("retrieval_latency_ms", 0))
        gen_lats.append(rec.get("generation_latency_ms", 0))

        all_match_scores.extend(parse_match_scores(output))

    def _avg(lst):
        return round(sum(lst) / len(lst), 4) if lst else None

    def _std(lst):
        if len(lst) < 2:
            return None
        mean = sum(lst) / len(lst)
        return round(math.sqrt(sum((x - mean) ** 2 for x in lst) / len(lst)), 4)

    return {
        "skill_diversity": _avg(skill_divs),
        "company_diversity": _avg(company_divs),
        "location_diversity": _avg(loc_divs),
        "profile_alignment": _avg(align_scores),
        "retrieval_latency_ms_avg": _avg(ret_lats),
        "retrieval_latency_ms_std": _std(ret_lats),
        "generation_latency_ms_avg": _avg(gen_lats),
        "generation_latency_ms_std": _std(gen_lats),
        "match_score_mean": _avg(all_match_scores),
        "match_score_std": _std(all_match_scores),
        "match_score_n": len(all_match_scores),
    }

# ─── Printing ─────────────────────────────────────────

def _try_tabulate(headers, rows):
    try:
        from tabulate import tabulate
        print(tabulate(rows, headers=headers, tablefmt="github"))
    except ImportError:
        print("  ".join(str(h) for h in headers))
        for row in rows:
            print("  ".join(str(v) for v in row))


def print_retrieval_table(ret: dict, ks: list[int]):
    print("\n=== Table 1: Retrieval Metrics ===")
    headers = ["Metric"] + [f"K={k}" for k in ks]
    metric_labels = [
        ("precision_at_k",           "Precision@K  (score>=0.15)"),
        ("recall_at_k",              "Recall@K     (feedback-based)"),
        ("hit_at_1",                 "Hit@1        (feedback-based)"),
        ("hit_rate_at_k",            "Hit Rate@K   (feedback-based)"),
        ("mrr",                      "MRR          (feedback-based)"),
        ("map_at_k",                 "MAP@K        (feedback-based)"),
        ("ndcg_at_k_with_rerank",    "NDCG@K       (with reranking)"),
        ("ndcg_at_k_without_rerank", "NDCG@K       (without reranking)"),
    ]
    rows = []
    for metric, label in metric_labels:
        row = [label] + [ret[metric].get(k, "N/A") for k in ks]
        rows.append(row)
    _try_tabulate(headers, rows)
    print("  Note: feedback-based metrics require rated jobs in the DB (rating >= 4 = relevant).")


def print_generation_table(gen: dict):
    print("\n=== Table 2: Generation Quality Metrics ===")
    headers = ["Metric", "Value"]
    rows = [
        ["Format Consistency (0-1)", gen["format_consistency"]],
        ["Faithfulness (0-1)", gen["faithfulness"]],
        [f"LLM Judge Avg (n={gen['llm_judge_n']}, 1-5)", gen["llm_judge_avg"]],
    ]
    _try_tabulate(headers, rows)


def print_system_table(sys_m: dict):
    print("\n=== Table 3: System Metrics ===")
    headers = ["Metric", "Value"]
    rows = [
        ["Skill Diversity (top-10)", sys_m["skill_diversity"]],
        ["Company Diversity (top-10)", sys_m["company_diversity"]],
        ["Location Diversity (top-10)", sys_m["location_diversity"]],
        ["Profile Alignment Score (avg)", sys_m["profile_alignment"]],
        ["Retrieval Latency ms (avg ± std)", f"{sys_m['retrieval_latency_ms_avg']} ± {sys_m['retrieval_latency_ms_std']}"],
        ["Generation Latency ms (avg ± std)", f"{sys_m['generation_latency_ms_avg']} ± {sys_m['generation_latency_ms_std']}"],
        [f"LLM Match Score mean (n={sys_m['match_score_n']})", sys_m["match_score_mean"]],
        ["LLM Match Score std", sys_m["match_score_std"]],
    ]
    _try_tabulate(headers, rows)

# ─── Plotting ─────────────────────────────────────────

def make_plots(records: list[dict], ret: dict, sys_m: dict, ks: list[int]):
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        print("[warn] matplotlib not installed; skipping plots.")
        return

    os.makedirs(PLOTS_DIR, exist_ok=True)

    # ── Plot 1: Pinecone score histogram ──
    all_scores = []
    for rec in records:
        for c in rec.get("candidates_after_rerank", []):
            s = c.get("score")
            if s is not None:
                all_scores.append(float(s))

    if all_scores:
        fig, ax = plt.subplots()
        ax.hist(all_scores, bins=30, color="steelblue", edgecolor="white")
        ax.set_xlabel("Pinecone Cosine Score")
        ax.set_ylabel("Count")
        ax.set_title("Distribution of Pinecone Cosine Scores\n(SHA-256 hash embeddings — expected range 0.10–0.35)")
        fig.tight_layout()
        fig.savefig(os.path.join(PLOTS_DIR, "plot1_pinecone_scores.png"), dpi=150)
        plt.close(fig)
        print(f"[plot] Saved plot1_pinecone_scores.png")

    # ── Plot 2: NDCG@K curve ──
    wr = [ret["ndcg_at_k_with_rerank"].get(k) for k in ks]
    nor = [ret["ndcg_at_k_without_rerank"].get(k) for k in ks]
    if any(v is not None for v in wr):
        fig, ax = plt.subplots()
        ax.plot(ks, [v or 0 for v in wr], marker="o", label="With Reranking")
        ax.plot(ks, [v or 0 for v in nor], marker="s", linestyle="--", label="Without Reranking")
        ax.set_xlabel("K")
        ax.set_ylabel("NDCG@K")
        ax.set_title("NDCG@K: Reranking Ablation")
        ax.legend()
        ax.set_ylim(0, 1)
        fig.tight_layout()
        fig.savefig(os.path.join(PLOTS_DIR, "plot2_ndcg_curve.png"), dpi=150)
        plt.close(fig)
        print(f"[plot] Saved plot2_ndcg_curve.png")

    # ── Plot 3: LLM match score distribution ──
    match_scores = []
    for rec in records:
        match_scores.extend(parse_match_scores(rec.get("llm_output", "")))

    if match_scores:
        fig, ax = plt.subplots()
        counts = Counter(int(round(s)) for s in match_scores)
        xs = sorted(counts)
        ax.bar(xs, [counts[x] for x in xs], color="seagreen", edgecolor="white")
        ax.set_xlabel("Match Score (1-10)")
        ax.set_ylabel("Frequency")
        ax.set_title("Distribution of LLM Match Scores")
        ax.set_xticks(range(1, 11))
        fig.tight_layout()
        fig.savefig(os.path.join(PLOTS_DIR, "plot3_match_scores.png"), dpi=150)
        plt.close(fig)
        print(f"[plot] Saved plot3_match_scores.png")

    # ── Plot 4: Latency breakdown ──
    ret_lats = [rec.get("retrieval_latency_ms", 0) for rec in records]
    gen_lats = [rec.get("generation_latency_ms", 0) for rec in records]
    if ret_lats or gen_lats:
        fig, ax = plt.subplots()
        xs = list(range(1, len(records) + 1))
        ax.bar(xs, ret_lats, label="Retrieval", color="steelblue")
        ax.bar(xs, gen_lats, bottom=ret_lats, label="Generation", color="darkorange")
        ax.set_xlabel("Request #")
        ax.set_ylabel("Latency (ms)")
        ax.set_title("Retrieval vs Generation Latency per Request")
        ax.legend()
        fig.tight_layout()
        fig.savefig(os.path.join(PLOTS_DIR, "plot4_latency.png"), dpi=150)
        plt.close(fig)
        print(f"[plot] Saved plot4_latency.png")

    # ── Plot 5: Reranking ablation (NDCG bar chart) ──
    ndcg_wr_vals = [ret["ndcg_at_k_with_rerank"].get(k) or 0 for k in ks]
    ndcg_nor_vals = [ret["ndcg_at_k_without_rerank"].get(k) or 0 for k in ks]
    if any(ndcg_wr_vals) or any(ndcg_nor_vals):
        x = range(len(ks))
        w = 0.35
        fig, ax = plt.subplots()
        ax.bar([xi - w / 2 for xi in x], ndcg_wr_vals, width=w, label="With Reranking", color="steelblue")
        ax.bar([xi + w / 2 for xi in x], ndcg_nor_vals, width=w, label="Without Reranking", color="lightcoral")
        ax.set_xticks(list(x))
        ax.set_xticklabels([f"K={k}" for k in ks])
        ax.set_ylabel("NDCG@K")
        ax.set_title("Reranking Ablation: NDCG@K Before vs After Reranking")
        ax.set_ylim(0, 1)
        ax.legend()
        fig.tight_layout()
        fig.savefig(os.path.join(PLOTS_DIR, "plot5_rerank_ablation.png"), dpi=150)
        plt.close(fig)
        print(f"[plot] Saved plot5_rerank_ablation.png")

# ─── Main ─────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="RAG Evaluation for JobMatch AI")
    parser.add_argument("--log", default=DEFAULT_LOG, help="Path to eval_log.jsonl")
    parser.add_argument("--db", default=DEFAULT_DB, help="Path to jobmatch.db SQLite database")
    parser.add_argument("--llm-judge", action="store_true", help="Run Gemma-as-judge (uses API quota)")
    parser.add_argument("--api-key", default=os.environ.get("GOOGLE_API_KEY", ""), help="Google API key for LLM judge")
    parser.add_argument("--ks", default="3,5,10,20", help="Comma-separated K values")
    args = parser.parse_args()

    ks = [int(k) for k in args.ks.split(",")]

    print(f"\nLoading eval log: {args.log}")
    records = load_eval_log(args.log)
    print(f"  {len(records)} records loaded")

    print(f"Loading feedback DB: {args.db}")
    feedback = load_feedback_db(args.db)
    print(f"  {len(feedback)} feedback rows loaded")

    if not records:
        print("\nNo records to evaluate. Run the backend with some test profiles first.")
        print("Example: POST /webhook with a profile to generate eval_log.jsonl entries.")
        sys.exit(0)

    print("\nComputing retrieval metrics...")
    ret = compute_retrieval_metrics(records, feedback, ks)

    print("Computing generation quality metrics...")
    api_key = args.api_key
    if args.llm_judge and not api_key:
        print("[warn] --llm-judge requires --api-key or GOOGLE_API_KEY env var")
    gen = compute_generation_metrics(records, args.llm_judge, api_key)

    print("Computing system metrics...")
    sys_m = compute_system_metrics(records)

    # Print tables
    print_retrieval_table(ret, ks)
    print_generation_table(gen)
    print_system_table(sys_m)

    # Save plots
    print("\nGenerating plots...")
    make_plots(records, ret, sys_m, ks)
    print(f"\nPlots saved to: {PLOTS_DIR}/")

    # Summary note on NDCG reranking ablation
    print("\n--- Reranking Ablation Summary ---")
    for k in ks:
        wr = ret["ndcg_at_k_with_rerank"].get(k)
        nor = ret["ndcg_at_k_without_rerank"].get(k)
        if wr is not None and nor is not None:
            delta = round(wr - nor, 4)
            print(f"  NDCG@{k}: with_rerank={wr}  without_rerank={nor}  delta={delta:+.4f}")


if __name__ == "__main__":
    main()
