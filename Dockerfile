FROM python:3.11-slim

WORKDIR /app

# System deps for edge-tts / reportlab etc.
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
RUN mkdir -p data

ENV PORT=8000
EXPOSE 8000

# init-db creates tables, ingest pulls first data (best-effort - won't fail the build/start
# if an external API hiccups), then start the API + hourly scheduler.
CMD python -m suraksha init-db && \
    (python -m suraksha ingest || true) && \
    python -m suraksha run --host 0.0.0.0 --port ${PORT}
