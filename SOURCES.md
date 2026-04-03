# External Source Catalog (One Listing = One Document)

This project now supports enriching the index with multiple external providers.
Each job listing is normalized into one document before embedding and upsert.

## Added Sources (7)

1. USAJOBS API  
   Link: https://developer.usajobs.gov/API-Reference  
   Notes: Official U.S. federal jobs feed, high-quality structured fields.

2. Adzuna API  
   Link: https://developer.adzuna.com/  
   Notes: Large aggregator across regions; salary and category metadata available.

3. Remotive Remote Jobs API  
   Link: https://github.com/remotive-io/remote-jobs-api  
   Notes: Remote-focused postings with categories/tags.

4. Arbeitnow Job Board API  
   Link: https://www.arbeitnow.com/api/job-board-api  
   Notes: Public remote/international listings with clean JSON format.

5. Jooble API  
   Link: https://jooble.org/api/about  
   Notes: Broad aggregator feed with location/keyword search.

6. Greenhouse Job Board API  
   Link: https://developers.greenhouse.io/job-board.html  
   Notes: Company ATS postings via board token; useful for startup/tech roles.

7. Lever Postings API  
   Link: https://github.com/lever/postings-api  
   Notes: Company ATS postings via site name; strong coverage for product/tech roles.

## How It Is Wired

- File: `source_ingestion.py`
- Entry point: `fetch_configured_sources()`
- Enabled by: `ENABLE_EXTERNAL_SOURCES=true`
- Indexed in: `backend.py` inside `index_dataset()`

## Configuration

Set these in `.env` as needed:

- `ENABLE_EXTERNAL_SOURCES`
- `USAJOBS_API_KEY`, `USAJOBS_API_EMAIL`
- `ADZUNA_APP_ID`, `ADZUNA_APP_KEY`
- `JOOBLE_API_KEY`, `JOOBLE_KEYWORDS`, `JOOBLE_LOCATION`, `JOOBLE_PAGE`
- `GREENHOUSE_BOARD_TOKENS` (comma-separated)
- `LEVER_SITE_NAMES` (comma-separated)

Remotive and Arbeitnow are public and do not require keys.

## Normalized Document Shape

Each listing is normalized to this schema:

- `job_id`, `title`, `role`, `company`, `location`, `country`
- `work_type`, `company_size`, `experience`, `qualifications`
- `salary`, `description`, `responsibilities`
- `skills`, `benefits`, `sector`, `industry`
- `posting_date`, `portal`, `source`, `external_url`

This keeps retrieval consistent while preserving source attribution.
