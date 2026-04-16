#!/usr/bin/env python3
"""Check AI layer configuration and dependencies"""
import os
import sys

print("=" * 60)
print("AI LAYER CONFIGURATION CHECK")
print("=" * 60)

# Check API key
openai_key = os.getenv('OPENAI_API_KEY')
print(f"\n✓ OPENAI_API_KEY: {'SET ✓' if openai_key else 'NOT SET ✗ (AI features will fail)'}")

# Check Chat Model
chat_model = os.getenv('OPENAI_CHAT_MODEL', 'gpt-4o')
print(f"✓ CHAT_MODEL: {chat_model}")

# Check packages
print("\nPackage Dependencies:")
packages = {
    'pdfplumber': 'PDF resume parsing',
    'resend': 'Email sending',
    'aiosqlite': 'Database (async)',
    'openai': 'OpenAI API client',
    'pinecone': 'Vector search (job embeddings)',
    'fastapi': 'Web framework',
}

missing = []
for pkg, desc in packages.items():
    try:
        __import__(pkg)
        print(f"  ✓ {pkg:20s} - {desc}")
    except ImportError:
        print(f"  ✗ {pkg:20s} - {desc} [MISSING]")
        missing.append(pkg)

# Check DB
print("\nDatabase Schema:")
try:
    import sqlite3
    db = sqlite3.connect('./data/jobmatch.db')
    cursor = db.cursor()
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
    tables = [row[0] for row in cursor.fetchall()]
    print(f"  Found {len(tables)} tables:")
    
    # Check for AI-related tables
    ai_tables = ['resume_enhancements', 'resume_tailoring', 'bookmarks', 'applications']
    for t in ai_tables:
        status = "✓" if t in tables else "✗"
        print(f"    {status} {t}")
    
    db.close()
except Exception as e:
    print(f"  ✗ Database check failed: {e}")

print("\n" + "=" * 60)
print("AI LAYER ENDPOINTS AVAILABLE:")
print("=" * 60)
endpoints = {
    'POST /parse-resume': 'Extract profile from PDF',
    'POST /enhance-resume': 'Score resume quality',
    'POST /tailor-resume': 'Tailor resume for job',
    'POST /keyword-gap': 'Analyze keyword match',
    'POST /cover-letter': 'Generate cover letter',
    'GET /resume-enhancements/{sid}': 'Retrieve enhancements',
    'GET /resume-tailoring/{sid}': 'Retrieve tailoring suggestions',
}
for ep, desc in endpoints.items():
    print(f"  • {ep:40s} - {desc}")

print("\n" + "=" * 60)
if missing:
    print(f"\n⚠ MISSING PACKAGES: {', '.join(missing)}")
    print("\nTo fix, run:")
    print(f"  pip install {' '.join(missing)}")
    sys.exit(1)
else:
    print("\n✓ All dependencies present - AI layer should work!")
    sys.exit(0)
