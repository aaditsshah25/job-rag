# Dataset Handoff

Use the generated CSV outside Git because `data/` is intentionally ignored. The final CSV is:

```text
data/adzuna_india_jobs_10000.csv
```

It contains 10,000 job rows plus the header row and is about 7.1 MB. Share this file directly with the teammate who will ingest it into Pinecone.

## Recommended Share Method

Do not commit the CSV, local database, or `.env` to GitHub. Send only the CSV through a direct file transfer channel such as Google Drive, OneDrive, Dropbox, or email attachment.

## Receiver Setup

1. Clone the repo and install dependencies:

```bash
pip install -r requirements.txt
```

2. Copy `.env.example` to `.env`.

3. Put the CSV at:

```text
data/adzuna_india_jobs_10000.csv
```

4. Add these settings to `.env`:

```env
CSV_PATH=./data/adzuna_india_jobs_10000.csv
INDEX_MODE=csv_only
ENABLE_EXTERNAL_SOURCES=false
PINECONE_API_KEY=<their-pinecone-key>
PINECONE_INDEX=job-listings1
PINECONE_CLOUD=aws
PINECONE_REGION=us-east-1
JOBMATCH_API_KEY=<any-shared-random-api-key>
```

5. Start the backend:

```bash
uvicorn backend:app --reload --port 8000
```

6. Force indexing into Pinecone:

```bash
curl -X POST "http://localhost:8000/index?force=true" -H "X-Api-Key: <JOBMATCH_API_KEY>"
```

The response should return `{"status":"ok","indexed":10000}` or a higher number if additional sources are enabled.
