"""
eval.py — Standalone RAG evaluation script for JobMatch AI

Pipeline overview:
  - Retrieval: user profile → hash-based embedding → Pinecone cosine search → top-20 candidates
  - Reranking: keyword-boost reranker re-orders the 20 candidates
  - Generation: Gemma receives top-10 candidates, outputs markdown with 5 ranked jobs + Match Score N/10

Ground truth approach (no annotated dataset):
  - Relevance signal 1: LLM match scores (1–10) — Gemma's own ranking of the 5 jobs it selected
  - Relevance signal 2: Pinecone cosine score — lexical overlap proxy (hash embeddings, range 0.17–0.45)
  - Relevance signal 3: User feedback ratings from SQLite (rating >= 4 = relevant), if available

Usage:
    python eval.py                       # all metrics + plots
    python eval.py --llm-judge           # also run Gemma-as-judge (uses API quota)
    python eval.py --log eval_log.jsonl --db data/jobmatch.db
"""

import argparse
import json
import math
import os
import re
import sqlite3
import sys
from collections import Counter
from urllib.request import Request as UrlRequest, urlopen

DEFAULT_LOG = os.path.join(os.path.dirname(__file__), "eval_log.jsonl")
DEFAULT_DB  = os.path.join(os.path.dirname(__file__), "data", "jobmatch.db")
PLOTS_DIR   = os.path.join(os.path.dirname(__file__), "eval_plots")

# ─── Data Loading ─────────────────────────────────────

def load_eval_log(path: str = DEFAULT_LOG) -> list[dict]:
    records = []
    if not os.path.exists(path):
        print(f"[warn] eval_log not found at {path}")
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

# ─── LLM Output Parsing ───────────────────────────────

def parse_scored_jobs(output: str) -> list[tuple[str, float]]:
    """
    Parse the LLM output to extract (job_title, match_score) pairs.
    Gemma outputs blocks like:
        ### <Title> @ <Company>
        - **Match Score: N/10 | ...**
    Returns list of (normalised_title, score) in output order.
    """
    results = []
    # Split on ### job blocks
    blocks = re.split(r"\n(?=###\s)", output)
    for block in blocks:
        title_match = re.match(r"###\s+(.+?)(?:\s+@\s+|\s*\n)", block)
        score_match = re.search(r"[Mm]atch\s+[Ss]core[:\s]+(\d+(?:\.\d+)?)\s*/\s*10", block)
        if title_match and score_match:
            title = title_match.group(1).strip().lower()
            score = float(score_match.group(1))
            results.append((title, score))
    return results


def parse_match_scores(output: str) -> list[float]:
    """Extract all Match Score values in order of appearance."""
    return [float(x) for x in re.findall(r"[Mm]atch\s+[Ss]core[:\s]+(\d+(?:\.\d+)?)\s*/\s*10", output)]


def _build_relevance_vector(candidates: list[dict], scored_jobs: list[tuple[str, float]]) -> list[float]:
    """
    Map LLM match scores onto the candidate list by title matching.
    Returns a relevance vector of length len(candidates): matched positions
    get score/10, unmatched positions get 0.
    This is the key fix: NDCG is computed over ALL candidates, not just the 5 scored ones.
    """
    rel = [0.0] * len(candidates)
    for title, score in scored_jobs:
        for i, c in enumerate(candidates):
            c_title = c.get("title", "").lower().strip()
            # Match if scored title is a substring of candidate title or vice versa
            if title in c_title or c_title in title or title[:30] == c_title[:30]:
                rel[i] = score / 10.0
                break
    return rel

# ─── Retrieval Metrics ────────────────────────────────

def precision_at_k(candidates: list[dict], k: int) -> float:
    """
    Precision@K using a relative threshold: a candidate is 'relevant' if its
    Pinecone score is >= the median score of all candidates in this result set.
    This avoids the trivial P@K=1.0 that results from a fixed threshold when
    all scores are above it (hash embeddings range 0.17–0.45, all > 0.15).
    """
    top = candidates[:k]
    if not top:
        return 0.0
    all_scores = sorted([float(c.get("score", 0)) for c in candidates], reverse=True)
    # Median of the full result set
    n = len(all_scores)
    median = (all_scores[n // 2 - 1] + all_scores[n // 2]) / 2 if n % 2 == 0 else all_scores[n // 2]
    relevant = sum(1 for c in top if float(c.get("score", 0)) >= median)
    return relevant / len(top)


def recall_at_k(retrieved: list[str], relevant: list[str], k: int) -> float:
    if not relevant:
        return 0.0
    top = set(t.lower().strip() for t in retrieved[:k])
    return sum(1 for r in relevant if r.lower().strip() in top) / len(relevant)


def hit_at_k(retrieved: list[str], relevant: list[str], k: int) -> float:
    """1 if any relevant item appears in top-K, else 0."""
    top = set(t.lower().strip() for t in retrieved[:k])
    return 1.0 if any(r.lower().strip() in top for r in relevant) else 0.0


def reciprocal_rank(retrieved: list[str], relevant: list[str]) -> float:
    relevant_set = {r.lower().strip() for r in relevant}
    for i, t in enumerate(retrieved, start=1):
        if t.lower().strip() in relevant_set:
            return 1.0 / i
    return 0.0


def average_precision(retrieved: list[str], relevant: list[str], k: int) -> float:
    relevant_set = {r.lower().strip() for r in relevant}
    hits, precision_sum = 0, 0.0
    for i, t in enumerate(retrieved[:k], start=1):
        if t.lower().strip() in relevant_set:
            hits += 1
            precision_sum += hits / i
    return precision_sum / len(relevant_set) if relevant_set else 0.0


def ndcg_at_k(relevances: list[float], k: int) -> float:
    """
    Standard NDCG@K. relevances[i] is the grade for the i-th item in the ranked list.
    Grades are LLM match scores normalised to [0,1]: score/10.
    Unranked candidates (not in LLM output) receive grade 0.
    """
    top = relevances[:k]
    if not top or all(r == 0 for r in top):
        return 0.0

    def dcg(rels):
        return sum((2 ** r - 1) / math.log2(i + 2) for i, r in enumerate(rels))

    idcg = dcg(sorted(top, reverse=True))
    return dcg(top) / idcg if idcg > 0 else 0.0

# ─── Generation Quality Metrics ───────────────────────

_FORMAT_RULES = [
    (r"# Your Job Match Results",          "has_main_heading"),
    (r"## Top Job Matches",                "has_subheading"),
    (r"### \S",                            "has_job_blocks"),
    (r"\*\*(?:Company|Role)\*\*[:\s]",    "has_company_or_role_field"),
    (r"\*\*Location\*\*[:\s]",            "has_location_field"),
    (r"[Mm]atch\s+[Ss]core[:\s]+\d+/10", "has_match_score"),
    (r"\*\*(?:Why|Reason|Because)",        "has_why_section"),
    (r"\[Apply|Apply Link|Apply Here",     "has_apply_link"),
]

def format_consistency_checks(output: str) -> dict:
    return {name: bool(re.search(pattern, output)) for pattern, name in _FORMAT_RULES}


def faithfulness_score(output: str, candidates: list[dict]) -> float:
    """
    Checks if job titles mentioned in LLM output (### blocks) exist in retrieved candidates.
    A hallucinated job would have a title not matching any candidate.
    """
    candidate_titles = [c.get("title", "").lower().strip() for c in candidates]
    mentioned_titles = [t for t, _ in parse_scored_jobs(output)]
    if not mentioned_titles:
        return 1.0
    found = 0
    for mt in mentioned_titles:
        if any(mt in ct or ct in mt or mt[:25] == ct[:25] for ct in candidate_titles):
            found += 1
    return found / len(mentioned_titles)

# ─── System / Diversity Metrics ───────────────────────

def skill_diversity(candidates: list[dict], k: int) -> float:
    all_skills = []
    for c in candidates[:k]:
        all_skills.extend(s.lower().strip() for s in (c.get("skills") or []) if s.strip())
    if not all_skills:
        return 0.0
    return len(set(all_skills)) / len(all_skills)


def company_diversity(candidates: list[dict], k: int) -> float:
    companies = [c.get("company", "").lower().strip() for c in candidates[:k] if c.get("company")]
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
    Weighted score (0–1) measuring how well a single job aligns with the profile.
    Components: skill overlap (0.5), location match (0.2), work type (0.15), salary (0.15).
    """
    score = 0.0

    p_skills = {s.lower().strip() for s in (profile.get("skills") or []) if s.strip()}
    j_skills = {s.lower().strip() for s in (job.get("skills") or []) if s.strip()}
    if p_skills:
        score += 0.5 * len(p_skills & j_skills) / len(p_skills)

    p_loc = (profile.get("location") or "").lower().strip()
    j_loc = (job.get("location") or "").lower().strip()
    if p_loc and j_loc and (p_loc in j_loc or j_loc in p_loc):
        score += 0.2

    p_wt = (profile.get("workType") or "Any").lower()
    j_wt = (job.get("work_type") or "").lower()
    if p_wt not in ("any", "") and j_wt and (p_wt in j_wt or j_wt in p_wt):
        score += 0.15

    p_sal = profile.get("salaryMin")
    j_sal_nums = re.findall(r"\d+", re.sub(r",", "", job.get("salary", "") or ""))
    if p_sal and j_sal_nums:
        try:
            if max(int(n) for n in j_sal_nums) >= int(p_sal):
                score += 0.15
        except (ValueError, TypeError):
            pass

    return round(score, 4)

# ─── LLM-as-Judge ─────────────────────────────────────

def llm_judge(profile_summary: str, output: str, api_key: str, model: str = "gemma-3-27b-it") -> int:
    """Ask Gemma to score recommendation relevance 1–5. Returns -1 on failure."""
    prompt = (
        "You are evaluating a job recommendation system. "
        "Given the user profile, rate how relevant the recommended jobs are on a scale of 1 to 5 "
        "(1=irrelevant, 3=somewhat relevant, 5=highly relevant). Reply with ONLY the integer.\n\n"
        f"USER PROFILE:\n{profile_summary}\n\n"
        f"RECOMMENDATIONS (first 1500 chars):\n{output[:1500]}\n\nScore (1-5):"
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
        print(f"  [llm-judge] error: {e}")
        return -1

# ─── Aggregate Computation ────────────────────────────

def _avg(lst):
    return round(sum(lst) / len(lst), 4) if lst else None

def _std(lst):
    if len(lst) < 2:
        return None
    mean = sum(lst) / len(lst)
    return round(math.sqrt(sum((x - mean) ** 2 for x in lst) / len(lst)), 4)


def compute_retrieval_metrics(records: list[dict], feedback: list[dict], ks: list[int]) -> dict:
    # Build session -> liked titles map from feedback
    session_liked: dict[str, list[str]] = {}
    for row in feedback:
        if int(row.get("rating", 0)) >= 4:
            session_liked.setdefault(row["session_id"], []).append(row["job_title"])

    results = {m: {} for m in [
        "precision_at_k", "recall_at_k", "hit_at_1", "hit_at_k",
        "mrr", "map_at_k",
        "ndcg_at_k_with_rerank", "ndcg_at_k_without_rerank",
    ]}

    for k in ks:
        p_vals, rec_vals, hit1_vals, hitk_vals = [], [], [], []
        rr_vals, ap_vals = [], []
        ndcg_wr_vals, ndcg_nor_vals = [], []

        for rec in records:
            after  = rec.get("candidates_after_rerank", [])
            before = rec.get("candidates_before_rerank", [])
            output = rec.get("llm_output", "")

            # ── Precision@K (Pinecone score relative threshold) ──
            p_vals.append(precision_at_k(after, k))

            # ── NDCG@K with and without reranking ──
            # Key fix: build relevance vectors by matching LLM-scored titles to
            # the actual candidate lists. NDCG reflects ordering quality over
            # all K positions, not just the 5 that Gemma scored.
            scored_jobs = parse_scored_jobs(output)
            if scored_jobs:
                rel_after  = _build_relevance_vector(after, scored_jobs)
                rel_before = _build_relevance_vector(before, scored_jobs)
                ndcg_wr_vals.append(ndcg_at_k(rel_after, k))
                ndcg_nor_vals.append(ndcg_at_k(rel_before, k))

            # ── Feedback-based metrics ──
            sid = rec.get("profile", {}).get("sessionId") or rec.get("session_id", "")
            liked = session_liked.get(sid, [])
            if liked:
                after_titles = [c.get("title", "") for c in after]
                rec_vals.append(recall_at_k(after_titles, liked, k))
                hit1_vals.append(hit_at_k(after_titles, liked, 1))
                hitk_vals.append(hit_at_k(after_titles, liked, k))
                rr_vals.append(reciprocal_rank(after_titles, liked))
                ap_vals.append(average_precision(after_titles, liked, k))

        results["precision_at_k"][k]           = _avg(p_vals)
        results["recall_at_k"][k]              = _avg(rec_vals)
        results["hit_at_1"][k]                 = _avg(hit1_vals)
        results["hit_at_k"][k]                 = _avg(hitk_vals)
        results["mrr"][k]                      = _avg(rr_vals)
        results["map_at_k"][k]                 = _avg(ap_vals)
        results["ndcg_at_k_with_rerank"][k]    = _avg(ndcg_wr_vals)
        results["ndcg_at_k_without_rerank"][k] = _avg(ndcg_nor_vals)

    return results


def compute_generation_metrics(records: list[dict], run_llm_judge: bool, api_key: str = "") -> dict:
    format_scores, faith_scores, judge_scores = [], [], []
    format_breakdown: dict[str, list[bool]] = {}

    for rec in records:
        output = rec.get("llm_output", "")
        after  = rec.get("candidates_after_rerank", [])

        checks = format_consistency_checks(output)
        for k, v in checks.items():
            format_breakdown.setdefault(k, []).append(v)
        format_scores.append(sum(checks.values()) / len(checks))
        faith_scores.append(faithfulness_score(output, after))

        if run_llm_judge and api_key:
            profile = rec.get("profile", {})
            summary = (
                f"Role: {profile.get('desiredRole','N/A')}, "
                f"Skills: {', '.join(profile.get('skills',[])[:5])}, "
                f"Location: {profile.get('location','N/A')}, "
                f"Experience: {profile.get('experience','N/A')} years"
            )
            score = llm_judge(summary, output, api_key)
            if score > 0:
                judge_scores.append(score)

    return {
        "format_consistency_avg": _avg(format_scores),
        "faithfulness_avg": _avg(faith_scores),
        "llm_judge_avg": _avg(judge_scores),
        "llm_judge_n": len(judge_scores),
        "format_breakdown": {k: round(sum(v) / len(v), 3) for k, v in format_breakdown.items()},
    }


def compute_system_metrics(records: list[dict], k: int = 10) -> dict:
    skill_divs, company_divs, loc_divs, align_scores = [], [], [], []
    ret_lats, gen_lats, all_match_scores = [], [], []

    for rec in records:
        after   = rec.get("candidates_after_rerank", [])
        profile = rec.get("profile", {})
        output  = rec.get("llm_output", "")

        skill_divs.append(skill_diversity(after, k))
        company_divs.append(company_diversity(after, k))
        loc_divs.append(location_diversity(after, k))
        for job in after[:k]:
            align_scores.append(profile_alignment_score(profile, job))

        ret_lats.append(rec.get("retrieval_latency_ms", 0))
        gen_lats.append(rec.get("generation_latency_ms", 0))
        all_match_scores.extend(parse_match_scores(output))

    return {
        "skill_diversity":            _avg(skill_divs),
        "company_diversity":          _avg(company_divs),
        "location_diversity":         _avg(loc_divs),
        "profile_alignment":          _avg(align_scores),
        "retrieval_latency_ms_avg":   _avg(ret_lats),
        "retrieval_latency_ms_std":   _std(ret_lats),
        "generation_latency_ms_avg":  _avg(gen_lats),
        "generation_latency_ms_std":  _std(gen_lats),
        "match_score_mean":           _avg(all_match_scores),
        "match_score_std":            _std(all_match_scores),
        "match_score_n":              len(all_match_scores),
    }

# ─── Printing ─────────────────────────────────────────

def _tabulate(headers, rows):
    try:
        from tabulate import tabulate
        print(tabulate(rows, headers=headers, tablefmt="github", floatfmt=".4f"))
    except ImportError:
        print("  ".join(str(h) for h in headers))
        for row in rows:
            print("  ".join(str(v) if v is not None else "N/A" for v in row))


def _fmt(v):
    if v is None:
        return "N/A*"
    return round(v, 4)


def print_retrieval_table(ret: dict, ks: list[int]):
    print("\n=== Table 1: Retrieval Metrics ===")
    metric_labels = [
        ("precision_at_k",           "Precision@K  (relative threshold)"),
        ("ndcg_at_k_with_rerank",    "NDCG@K       (with reranking)"),
        ("ndcg_at_k_without_rerank", "NDCG@K       (without reranking)"),
        ("recall_at_k",              "Recall@K     (feedback-based)"),
        ("hit_at_1",                 "Hit@1        (feedback-based)"),
        ("hit_at_k",                 "Hit@K        (feedback-based)"),
        ("mrr",                      "MRR          (feedback-based)"),
        ("map_at_k",                 "MAP@K        (feedback-based)"),
    ]
    headers = ["Metric"] + [f"K={k}" for k in ks]
    rows = [[label] + [_fmt(ret[m].get(k)) for k in ks] for m, label in metric_labels]
    _tabulate(headers, rows)
    print("  * N/A = no user feedback ratings in DB (rating>=4 used as relevant)")


def print_generation_table(gen: dict):
    print("\n=== Table 2: Generation Quality Metrics ===")
    rows = [
        ["Format Consistency (avg, 0–1)", _fmt(gen["format_consistency_avg"])],
        ["Faithfulness (0–1)",            _fmt(gen["faithfulness_avg"])],
        [f"LLM Judge Relevance (1–5, n={gen['llm_judge_n']})", _fmt(gen["llm_judge_avg"])],
    ]
    _tabulate(["Metric", "Value"], rows)
    if gen["format_breakdown"]:
        print("\n  Format rule breakdown:")
        for rule, rate in sorted(gen["format_breakdown"].items()):
            bar = "#" * int(rate * 20)
            print(f"    {rule:<35} {rate:.2f}  {bar}")


def print_system_table(sys_m: dict):
    print("\n=== Table 3: System Metrics ===")
    rows = [
        ["Company Diversity (top-10)",             _fmt(sys_m["company_diversity"])],
        ["Location Diversity (top-10)",            _fmt(sys_m["location_diversity"])],
        ["Skill Diversity (top-10)",               _fmt(sys_m["skill_diversity"])],
        ["Profile Alignment Score (avg)",          _fmt(sys_m["profile_alignment"])],
        ["Retrieval Latency (avg ms)",             _fmt(sys_m["retrieval_latency_ms_avg"])],
        ["Retrieval Latency (std ms)",             _fmt(sys_m["retrieval_latency_ms_std"])],
        ["Generation Latency (avg ms)",            _fmt(sys_m["generation_latency_ms_avg"])],
        ["Generation Latency (std ms)",            _fmt(sys_m["generation_latency_ms_std"])],
        [f"LLM Match Score mean (n={sys_m['match_score_n']})", _fmt(sys_m["match_score_mean"])],
        ["LLM Match Score std",                    _fmt(sys_m["match_score_std"])],
    ]
    _tabulate(["Metric", "Value"], rows)

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

    # Plot 1: Pinecone score histogram
    all_scores = [float(c["score"]) for rec in records
                  for c in rec.get("candidates_after_rerank", []) if c.get("score") is not None]
    if all_scores:
        fig, ax = plt.subplots(figsize=(7, 4))
        ax.hist(all_scores, bins=25, color="steelblue", edgecolor="white")
        median = sorted(all_scores)[len(all_scores) // 2]
        ax.axvline(median, color="red", linestyle="--", label=f"Median = {median:.3f}")
        ax.set_xlabel("Pinecone Cosine Score")
        ax.set_ylabel("Count")
        ax.set_title("Pinecone Cosine Score Distribution\n(SHA-256 hash embeddings — lexical overlap only, range ~0.17–0.45)")
        ax.legend()
        fig.tight_layout()
        fig.savefig(os.path.join(PLOTS_DIR, "plot1_pinecone_scores.png"), dpi=150)
        plt.close(fig)
        print("  [plot] plot1_pinecone_scores.png")

    # Plot 2: NDCG@K curve (with vs without reranking)
    wr  = [ret["ndcg_at_k_with_rerank"].get(k) for k in ks]
    nor = [ret["ndcg_at_k_without_rerank"].get(k) for k in ks]
    if any(v is not None for v in wr):
        fig, ax = plt.subplots(figsize=(7, 4))
        ax.plot(ks, [v or 0 for v in wr],  marker="o", label="With Reranking",    color="steelblue")
        ax.plot(ks, [v or 0 for v in nor], marker="s", label="Without Reranking", color="lightcoral", linestyle="--")
        ax.set_xlabel("K")
        ax.set_ylabel("NDCG@K")
        ax.set_title("NDCG@K — Reranking Ablation")
        ax.set_ylim(0, 1.05)
        ax.legend()
        fig.tight_layout()
        fig.savefig(os.path.join(PLOTS_DIR, "plot2_ndcg_curve.png"), dpi=150)
        plt.close(fig)
        print("  [plot] plot2_ndcg_curve.png")

    # Plot 3: LLM match score distribution
    match_scores = [s for rec in records for s in parse_match_scores(rec.get("llm_output", ""))]
    if match_scores:
        fig, ax = plt.subplots(figsize=(7, 4))
        counts = Counter(int(round(s)) for s in match_scores)
        xs = sorted(counts)
        ax.bar(xs, [counts[x] for x in xs], color="seagreen", edgecolor="white", width=0.6)
        ax.set_xlabel("Match Score (out of 10)")
        ax.set_ylabel("Frequency")
        ax.set_title(f"LLM Match Score Distribution (n={len(match_scores)})\nGemma's self-assigned relevance scores")
        ax.set_xticks(range(1, 11))
        mean_s = sum(match_scores) / len(match_scores)
        ax.axvline(mean_s, color="red", linestyle="--", label=f"Mean = {mean_s:.2f}")
        ax.legend()
        fig.tight_layout()
        fig.savefig(os.path.join(PLOTS_DIR, "plot3_match_scores.png"), dpi=150)
        plt.close(fig)
        print("  [plot] plot3_match_scores.png")

    # Plot 4: Latency breakdown per request
    ret_lats = [rec.get("retrieval_latency_ms", 0) for rec in records]
    gen_lats = [rec.get("generation_latency_ms", 0) for rec in records]
    fig, ax = plt.subplots(figsize=(9, 4))
    xs = list(range(1, len(records) + 1))
    ax.bar(xs, ret_lats, label=f"Retrieval (avg {_avg(ret_lats):.0f}ms)", color="steelblue")
    ax.bar(xs, gen_lats, bottom=ret_lats, label=f"Generation (avg {_avg(gen_lats):.0f}ms)", color="darkorange")
    ax.set_xlabel("Request #")
    ax.set_ylabel("Latency (ms)")
    ax.set_title("End-to-End Latency Breakdown per Request")
    ax.legend()
    fig.tight_layout()
    fig.savefig(os.path.join(PLOTS_DIR, "plot4_latency.png"), dpi=150)
    plt.close(fig)
    print("  [plot] plot4_latency.png")

    # Plot 5: Reranking ablation bar chart
    ndcg_wr_vals  = [ret["ndcg_at_k_with_rerank"].get(k) or 0 for k in ks]
    ndcg_nor_vals = [ret["ndcg_at_k_without_rerank"].get(k) or 0 for k in ks]
    if any(ndcg_wr_vals) or any(ndcg_nor_vals):
        x, w = list(range(len(ks))), 0.35
        fig, ax = plt.subplots(figsize=(7, 4))
        ax.bar([xi - w/2 for xi in x], ndcg_wr_vals,  width=w, label="With Reranking",    color="steelblue")
        ax.bar([xi + w/2 for xi in x], ndcg_nor_vals, width=w, label="Without Reranking", color="lightcoral")
        ax.set_xticks(x)
        ax.set_xticklabels([f"K={k}" for k in ks])
        ax.set_ylabel("NDCG@K")
        ax.set_title("Reranking Ablation: NDCG@K Before vs After Reranking")
        ax.set_ylim(0, 1.05)
        ax.legend()
        fig.tight_layout()
        fig.savefig(os.path.join(PLOTS_DIR, "plot5_rerank_ablation.png"), dpi=150)
        plt.close(fig)
        print("  [plot] plot5_rerank_ablation.png")

# ─── Main ─────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="RAG Evaluation — JobMatch AI")
    parser.add_argument("--log",       default=DEFAULT_LOG)
    parser.add_argument("--db",        default=DEFAULT_DB)
    parser.add_argument("--llm-judge", action="store_true")
    parser.add_argument("--api-key",   default=os.environ.get("GOOGLE_API_KEY", ""))
    parser.add_argument("--ks",        default="3,5,10,20")
    args = parser.parse_args()

    ks = [int(k) for k in args.ks.split(",")]

    print(f"\nLoading eval log:  {args.log}")
    records = load_eval_log(args.log)
    print(f"  {len(records)} records")

    print(f"Loading feedback:  {args.db}")
    feedback = load_feedback_db(args.db)
    print(f"  {len(feedback)} feedback rows")

    if not records:
        print("\nNo records. Run seed_eval.py first.")
        sys.exit(0)

    print("\nComputing metrics...")
    ret   = compute_retrieval_metrics(records, feedback, ks)
    gen   = compute_generation_metrics(records, args.llm_judge, args.api_key)
    sys_m = compute_system_metrics(records)

    print_retrieval_table(ret, ks)
    print_generation_table(gen)
    print_system_table(sys_m)

    print("\nGenerating plots...")
    make_plots(records, ret, sys_m, ks)
    print(f"Plots saved to: {PLOTS_DIR}/")

    print("\n--- Reranking Ablation (NDCG delta) ---")
    for k in ks:
        wr  = ret["ndcg_at_k_with_rerank"].get(k)
        nor = ret["ndcg_at_k_without_rerank"].get(k)
        if wr is not None and nor is not None:
            print(f"  NDCG@{k:<3}: with={wr:.4f}  without={nor:.4f}  delta={wr-nor:+.4f}")


if __name__ == "__main__":
    main()
