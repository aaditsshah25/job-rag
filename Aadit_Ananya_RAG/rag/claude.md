# JobMatch AI Project Reference

This file is a compact technical reference for the JobMatch AI project. It is meant to help future developers or AI assistants understand how the app is structured, how data flows through it, and where to change specific behavior.

## Project Summary

JobMatch AI is a RAG-based job matching application built with:

- FastAPI for the backend
- OpenAI for embeddings, chat completion, resume parsing, and cover letter generation
- Pinecone for vector search over job listings
- SQLite for bookmarks, feedback, and related user actions
- A static HTML/CSS/JavaScript frontend

The main user flow is:

1. A user fills in a job-seeking profile or uploads a resume.
2. The backend turns that profile into a search query.
3. The query is embedded and matched against indexed job postings in Pinecone.
4. GPT-4o ranks the best matches and returns formatted markdown.
5. The frontend renders the response into structured cards.

## Repository Layout

Key files in this project:

- [backend.py](backend.py) - FastAPI app, indexing, retrieval, LLM prompts, and auxiliary APIs
- [requirements.txt](requirements.txt) - Python dependencies
- [frontend/index.html](frontend/index.html) - Main UI structure
- [frontend/app.js](frontend/app.js) - Form handling, API calls, result rendering, resume upload, bookmarking, email actions
- [frontend/style.css](frontend/style.css) - Visual styling and responsive layout
- [frontend/config.js](frontend/config.js) - Runtime config for API base URL and API key
- [frontend/data.js](frontend/data.js) - Curated job titles and skills lists for autocomplete
- [GENAI_RAG_Dataset - Sheet1.csv](GENAI_RAG_Dataset%20-%20Sheet1.csv) - Dataset of about 2,000 job listings
- [GenAI - RAG Assignment - Final.json](GenAI%20-%20RAG%20Assignment%20-%20Final.json) - Original workflow reference
- [Dockerfile](Dockerfile) - Container image for the backend
- [docker-compose.yml](docker-compose.yml) - Local container orchestration
- [railway.json](railway.json) - Railway deployment configuration
- [start.bat](start.bat) - Windows startup script

## Backend Overview

The backend is a single FastAPI app defined in [backend.py](backend.py). It handles:

- automatic dataset indexing on startup
- semantic search over job postings
- resume parsing from PDF
- cover letter generation
- bookmarks and feedback storage
- result email delivery through Resend

### Startup Behavior

On startup, the app:

1. Initializes the SQLite database tables if they do not exist.
2. If both OpenAI and Pinecone API keys are present, it tries to index the dataset automatically.

The local database path defaults to `./data/jobmatch.db`, and the Docker setup mounts `./data` so the database persists across container restarts.

### Data Flow for Job Matching

The matching pipeline works like this:

1. A profile or free-text request is converted into a query string.
2. The query is embedded with `text-embedding-3-small`.
3. Pinecone returns the most similar jobs from the indexed dataset.
4. GPT-4o receives the user profile and candidate jobs and returns a markdown summary with ranked matches.

The backend uses:

- a 10 minute TTL cache for repeated searches
- in-memory session history with a 60 minute TTL
- optional salary filtering when the query contains a salary threshold

### Dataset Indexing

Indexing reads `GENAI_RAG_Dataset - Sheet1.csv`, cleans each row, converts each job into a searchable text block, embeds the text in batches, and upserts vectors into Pinecone.

Important implementation notes:

- The Pinecone index is created automatically if it does not exist.
- The vector dimension is `1536` to match `text-embedding-3-small`.
- Metadata is stored with each vector so results can be shown as rich job cards.
- First startup can take several minutes because the full dataset is embedded and uploaded.

## API Endpoints

The backend exposes these routes:

- `GET /health` - health check and version
- `POST /webhook` - main job matching endpoint
- `POST /index` - re-index the dataset, optionally forced with `force=true`
- `POST /parse-resume` - extract structured profile data from a PDF resume
- `POST /cover-letter` - generate a tailored cover letter
- `POST /bookmark` - save a bookmarked job
- `GET /bookmarks/{session_id}` - fetch bookmarks for a session
- `POST /feedback` - store rating and feedback for a recommendation
- `POST /send-results` - email the generated markdown results

### Main Webhook Contract

Request body supports either:

```json
{
  "chatInput": "I am looking for a remote data analyst role",
  "sessionId": "session_123"
}
```

or:

```json
{
  "profile": {
    "name": "Aadit",
    "desiredRole": "Data Analyst",
    "skills": ["Python", "SQL"],
    "experience": 2
  },
  "sessionId": "session_123"
}
```

Response body:

```json
{
  "output": "# Your Job Match Results ..."
}
```

If no matches are found, the backend returns a plain helpful message instead of markdown cards.

## Frontend Overview

The frontend is static and does not require a build step.

### Main UI Behavior

The page in [frontend/index.html](frontend/index.html) contains:

- a profile form for job preferences
- a PDF resume upload area
- a results area that starts empty and then renders job cards
- controls for dark mode, clearing results, emailing results, and bookmarking

The JavaScript in [frontend/app.js](frontend/app.js) is responsible for:

- collecting form values
- maintaining a session ID in memory for the browser session
- adding and removing skill tags
- limiting benefit selections to 3
- calling the backend `/webhook` endpoint
- rendering markdown results into structured cards
- uploading PDFs to `/parse-resume`
- sending bookmarked jobs and feedback
- sending results by email via `/send-results`

### Autocomplete Data

[frontend/data.js](frontend/data.js) contains curated arrays for:

- job title suggestions
- common skills suggestions

These are used to make the form easier to fill out and to reduce input noise.

### Config

[frontend/config.js](frontend/config.js) expects runtime values injected into `window`:

- `window.JOBMATCH_API_URL`
- `window.JOBMATCH_API_KEY`

If no values are injected, it falls back to `http://localhost:8000` and no API key.

## Styling And Rendering

[frontend/style.css](frontend/style.css) defines the full visual system:

- a split panel layout with a sticky profile card on the left
- glass-style card surfaces
- custom tag inputs and checkbox styling
- responsive layout behavior
- theme variables for light and dark appearance

The frontend does not simply dump raw markdown. It parses the returned markdown into sections such as summary, matches, and next steps, then renders those into structured result cards. If parsing fails, it falls back to a simpler markdown display.

## Environment Variables

The backend reads configuration from environment variables, usually stored in a `.env` file.

Most important variables:

- `OPENAI_API_KEY` - required for embeddings, chat completions, and resume parsing
- `PINECONE_API_KEY` - required for vector search and indexing
- `PINECONE_INDEX` - Pinecone index name, default `job-listings1`
- `PINECONE_CLOUD` - default `aws`
- `PINECONE_REGION` - default `us-east-1`
- `OPENAI_CHAT_MODEL` - default `gpt-4o`
- `TOP_K` - number of Pinecone candidates to retrieve, default `20`
- `TOP_N_RESULTS` - number of final matches returned to the user, default `5`
- `CSV_PATH` - path to the job dataset CSV
- `DB_PATH` - SQLite database path, default `./data/jobmatch.db`
- `JOBMATCH_API_KEY` - optional API key protection for the backend
- `RESEND_API_KEY` - required to enable email sending
- `FROM_EMAIL` - sender address for results emails
- `ALLOWED_ORIGINS` - comma-separated CORS allowlist

## Deployment Options

### Local Windows Run

Use [start.bat](start.bat) from the project folder. It checks for `.env`, installs dependencies, and starts Uvicorn on port 8000.

### Docker

[Dockerfile](Dockerfile) installs Python dependencies and system packages needed by PDF parsing, then starts the FastAPI app.

[docker-compose.yml](docker-compose.yml) exposes port 8000, mounts the `data` folder, and passes environment variables from `.env`.

### Railway

[railway.json](railway.json) builds from the Dockerfile and starts the app with:

```bash
uvicorn backend:app --host 0.0.0.0 --port $PORT
```

## Important Runtime Notes

- The first boot may be slow because dataset indexing happens automatically.
- Resume parsing requires `pdfplumber` to be installed and only accepts PDF files.
- Email sending only works when `RESEND_API_KEY` is configured.
- The backend can be left open to all origins by default, but that can be tightened with `ALLOWED_ORIGINS`.
- If `JOBMATCH_API_KEY` is set, the frontend must send it as `X-Api-Key`.

## Where To Change Things

- Adjust matching logic, indexing, or prompts in [backend.py](backend.py)
- Change form fields or interaction behavior in [frontend/app.js](frontend/app.js)
- Update the page structure in [frontend/index.html](frontend/index.html)
- Modify styling in [frontend/style.css](frontend/style.css)
- Add or remove autocomplete values in [frontend/data.js](frontend/data.js)

## Short Mental Model

Think of the project as:

1. A static browser UI for collecting a candidate profile.
2. A FastAPI service that converts that profile into a semantic search query.
3. A Pinecone-backed retrieval layer over the CSV dataset.
4. An OpenAI ranking layer that turns search hits into readable recommendations.
5. Optional persistence features for bookmarks, feedback, resume parsing, and emailed results.