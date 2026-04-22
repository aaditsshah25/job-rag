FROM python:3.11-slim

# Install system dependencies for pdfplumber
RUN apt-get update && apt-get install -y \
    curl \
    libpoppler-cpp-dev \
    poppler-utils \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy backend and frontend
COPY backend.py source_ingestion.py ./
COPY frontend/ ./frontend/
COPY data/ ./data/

EXPOSE 8000

CMD ["uvicorn", "backend:app", "--host", "0.0.0.0", "--port", "8000"]
