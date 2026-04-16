# JobMatch AI (Final Job RAG) - One Page Product Summary

## 1) What we are building
JobMatch AI is an end-to-end Retrieval-Augmented Generation (RAG) application for personalized job discovery. The user enters a profile (role, experience, skills, location, salary preference, work type, and optional constraints), and the system retrieves relevant jobs from an indexed job corpus, then produces ranked recommendations with explanations and actionable next steps.

The product is not just a search interface. It combines semantic retrieval, reranking, and LLM reasoning to answer the practical question: "Which jobs are best for this specific candidate and why?"

## 2) What the current product does
The current product covers the full journey from profile capture to recommendation and follow-up:

- Profile intake via structured form in the frontend.
- Optional resume upload (PDF) and AI-based profile extraction.
- Retrieval from a vector index of job postings (local dataset plus optional external sources).
- Hybrid reranking (semantic + lexical + fit adjustments).
- LLM-generated recommendation report with:
  - summary statistics,
  - top matches,
  - match score,
  - fit reasons,
  - gap analysis,
  - recommended next steps.
- Utility workflows:
  - save bookmarks,
  - track application status (saved/applied/interview/offer/rejected),
  - submit feedback ratings,
  - generate tailored cover letters,
  - email results to the user.
- Basic authentication flow (Google sign-in + JWT, with local fallback mode).
- Rate limiting and API key checks for backend protection.

## 3) What exactly we are using (technical stack)
### Backend
- FastAPI for API layer.
- OpenAI API:
  - text-embedding-3-small for embeddings,
  - GPT-4o (configurable) for recommendation generation, resume parsing, and cover letter generation.
- Pinecone (serverless index, cosine similarity) as vector database.
- Pandas for CSV ingestion/cleaning.
- aiosqlite for persistence of bookmarks, feedback, and application tracking.
- slowapi + cachetools for rate limiting and TTL caching.
- pdfplumber for PDF resume text extraction.
- Resend API for emailing results.
- PyJWT + google-auth for auth tokens and Google credential verification.

### Retrieval and ranking design
- Candidate profile is converted into a rich query string.
- Query is embedded and used for Pinecone similarity retrieval.
- Optional salary filter is applied during retrieval.
- Retrieved candidates are reranked using:
  - semantic score (vector similarity),
  - lexical overlap score (title/skills/context token overlap),
  - fit adjustments (work mode and experience alignment).
- De-duplication prevents repeated title-company pairs.

### Data sources
- Primary local dataset: GENAI_RAG_Dataset - Sheet1.csv (about 2,000 rows).
- Optional external APIs via source_ingestion.py:
  - USAJOBS,
  - Adzuna,
  - Remotive,
  - Arbeitnow,
  - Jooble,
  - Greenhouse,
  - Lever.

### Frontend
- Vanilla HTML/CSS/JavaScript (no heavy framework dependency).
- Profile form with skill tags, advanced filters, dark mode, and result filters/sorting.
- Marketing landing shell + auth gate + dashboard flow.
- Config-driven API endpoint setup for local and deployed environments.

### Deployment/readiness
- Dockerfile for containerized backend deployment.
- Vercel-ready frontend config/build script.
- Support files for Railway/Nixpacks in mirrored deployment folder.

## 4) What else we can add (high-value next steps)
1. Better evaluation and observability
- Add offline retrieval metrics (Precision@K, Recall@K, nDCG) and online success metrics.
- Log model/ranking decisions and user click/apply outcomes for continuous tuning.

2. Personalized feedback loop
- Learn from user actions (bookmarks, applications, ratings) to reweight recommendations per user.
- Add "Why this changed" explanations after each interaction.

3. Smarter matching intelligence
- Add skill ontology/normalization (e.g., "PyTorch" ~= "Deep Learning framework").
- Add location-distance and visa/work authorization hard filters.
- Add compensation normalization by country/currency.

4. Data quality and freshness
- Scheduled reindex jobs with deduplication and stale posting removal.
- Source reliability scoring and broken-link detection.

5. Production hardening
- Move session/chat state from in-memory to Redis/Postgres for scale.
- Add role-based admin analytics view.
- Add robust test coverage (API contract tests + ranking regression tests).

## 5) Summary
JobMatch AI already delivers a complete RAG-based job recommendation product: data ingestion, vector retrieval, LLM ranking/explanations, and user action workflows in one system. The strongest immediate improvement path is to add measurable evaluation and user-feedback learning so recommendations become increasingly accurate over time.