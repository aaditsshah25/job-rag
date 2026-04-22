"""
seed_eval.py — sends test profiles to the Railway backend to populate eval_log.jsonl

Usage:
    python seed_eval.py --url https://YOUR-APP.railway.app --key YOUR_API_KEY
"""

import argparse
import json
import time
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

TEST_PROFILES = [
    {
        "profile": {
            "name": "Test User 1",
            "desiredRole": "Software Engineer",
            "experience": 3,
            "skills": ["Python", "FastAPI", "PostgreSQL", "Docker", "REST APIs"],
            "education": "B.Tech Computer Science",
            "industry": "Technology",
            "location": "Bangalore",
            "workType": "Full-time",
            "salaryMin": 800000,
        }
    },
    {
        "profile": {
            "name": "Test User 2",
            "desiredRole": "Data Scientist",
            "experience": 2,
            "skills": ["Python", "Machine Learning", "TensorFlow", "SQL", "Pandas"],
            "education": "M.Sc Data Science",
            "industry": "Analytics",
            "location": "Mumbai",
            "workType": "Full-time",
            "salaryMin": 1000000,
        }
    },
    {
        "profile": {
            "name": "Test User 3",
            "desiredRole": "Frontend Developer",
            "experience": 4,
            "skills": ["React", "TypeScript", "CSS", "Next.js", "GraphQL"],
            "education": "B.E Information Technology",
            "industry": "Technology",
            "location": "Hyderabad",
            "workType": "Remote",
            "salaryMin": 900000,
        }
    },
    {
        "profile": {
            "name": "Test User 4",
            "desiredRole": "Product Manager",
            "experience": 5,
            "skills": ["Product Strategy", "Agile", "Jira", "User Research", "Roadmapping"],
            "education": "MBA",
            "industry": "Technology",
            "location": "Delhi",
            "workType": "Full-time",
            "salaryMin": 1500000,
        }
    },
    {
        "profile": {
            "name": "Test User 5",
            "desiredRole": "DevOps Engineer",
            "experience": 3,
            "skills": ["Kubernetes", "AWS", "Terraform", "CI/CD", "Linux", "Docker"],
            "education": "B.Tech",
            "industry": "Cloud",
            "location": "Pune",
            "workType": "Full-time",
            "salaryMin": 1000000,
        }
    },
    {
        "profile": {
            "name": "Test User 6",
            "desiredRole": "Machine Learning Engineer",
            "experience": 2,
            "skills": ["Python", "PyTorch", "NLP", "LLMs", "Hugging Face", "MLOps"],
            "education": "M.Tech AI",
            "industry": "AI/ML",
            "location": "Bangalore",
            "workType": "Remote",
            "salaryMin": 1200000,
        }
    },
    {
        "profile": {
            "name": "Test User 7",
            "desiredRole": "Backend Engineer",
            "experience": 6,
            "skills": ["Java", "Spring Boot", "Microservices", "Kafka", "Redis"],
            "education": "B.Tech",
            "industry": "Fintech",
            "location": "Chennai",
            "workType": "Full-time",
            "salaryMin": 1800000,
        }
    },
    {
        "profile": {
            "name": "Test User 8",
            "desiredRole": "Data Analyst",
            "experience": 1,
            "skills": ["SQL", "Excel", "Power BI", "Tableau", "Python"],
            "education": "B.Com",
            "industry": "Finance",
            "location": "Mumbai",
            "workType": "Full-time",
            "salaryMin": 500000,
        }
    },
    {
        "profile": {
            "name": "Test User 9",
            "desiredRole": "Cloud Architect",
            "experience": 8,
            "skills": ["AWS", "Azure", "GCP", "Terraform", "Security", "Architecture"],
            "education": "B.Tech",
            "industry": "Cloud",
            "location": "Bangalore",
            "workType": "Full-time",
            "salaryMin": 2500000,
        }
    },
    {
        "profile": {
            "name": "Test User 10",
            "desiredRole": "Full Stack Developer",
            "experience": 3,
            "skills": ["React", "Node.js", "MongoDB", "Express", "AWS"],
            "education": "B.Tech",
            "industry": "Startup",
            "location": "Hyderabad",
            "workType": "Hybrid",
            "salaryMin": 900000,
        }
    },
]


def send_profile(url: str, api_key: str, payload: dict, idx: int) -> bool:
    body = json.dumps(payload).encode("utf-8")
    req = Request(
        f"{url.rstrip('/')}/webhook",
        data=body,
        headers={
            "Content-Type": "application/json",
            "x-api-key": api_key,
        },
        method="POST",
    )
    try:
        with urlopen(req, timeout=120) as resp:
            data = json.loads(resp.read())
            output_preview = (data.get("output", "") or "")[:80].replace("\n", " ")
            print(f"  [{idx+1}] OK — {output_preview}...")
            return True
    except HTTPError as e:
        print(f"  [{idx+1}] HTTP {e.code}: {e.read().decode()[:200]}")
        return False
    except URLError as e:
        print(f"  [{idx+1}] URLError: {e.reason}")
        return False
    except Exception as e:
        print(f"  [{idx+1}] Error: {e}")
        return False


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", required=True, help="Railway backend URL, e.g. https://yourapp.railway.app")
    parser.add_argument("--key", required=True, help="API key (x-api-key header)")
    parser.add_argument("--delay", type=float, default=3.0, help="Seconds between requests (default 3)")
    args = parser.parse_args()

    print(f"Sending {len(TEST_PROFILES)} test profiles to {args.url}/webhook")
    print(f"Delay between requests: {args.delay}s\n")

    ok = 0
    for i, payload in enumerate(TEST_PROFILES):
        print(f"Sending profile {i+1}/{len(TEST_PROFILES)}: {payload['profile']['desiredRole']} in {payload['profile']['location']}")
        if send_profile(args.url, args.key, payload, i):
            ok += 1
        if i < len(TEST_PROFILES) - 1:
            time.sleep(args.delay)

    print(f"\nDone: {ok}/{len(TEST_PROFILES)} successful")
    print("eval_log.jsonl should now have entries on the Railway server.")
    print("\nNext: download eval_log.jsonl from Railway or read it via the steps below.")


if __name__ == "__main__":
    main()
