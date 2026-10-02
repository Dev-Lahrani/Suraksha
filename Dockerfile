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

# Lifespan initializes storage and ingests in the background so health checks
# are available immediately, even during slow first-time archive requests.
CMD python -m suraksha run --host 0.0.0.0 --port ${PORT}
